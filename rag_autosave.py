import os
import uuid
import time
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
FORCE_RESET = os.environ.get("FORCE_RESET", "false").lower() == "true"
RAG_API_URL = os.environ.get("RAG_API_URL", "http://rag-api.railway.internal:8000")

USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

def save_to_rag(file_id, filename, content):
    import requests
    payload = {
        "documents": [{
            "page_content": content,
            "metadata": {
                "file_id": file_id,
                "filename": filename,
                "user": USER_ID
            }
        }]
    }
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(
            f"{RAG_API_URL}/documents",
            json=payload,
            headers=headers,
            timeout=30
        )
        return response.status_code, response.text[:200]
    except Exception as e:
        return 0, str(e)

def extract_text(content):
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ["text", "value", "content"]:
                    if key in item and item[key]:
                        parts.append(str(item[key]))
                        break
        return " ".join(parts)
    if isinstance(content, dict):
        for key in ["text", "value", "content"]:
            if key in content and content[key]:
                return str(content[key])
    return str(content)

def get_conversation_text(messages):
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = extract_text(msg.get("text") or msg.get("content", ""))
        if content.strip():
            lines.append(f"[{role}]: {content}")
    return "\n".join(lines)

def main():
    client = MongoClient(MONGO_URI)
    db = client.get_database("test")

    now = datetime.now(timezone.utc)

    if FORCE_RESET:
        since = datetime(2020, 1, 1)
    else:
        state = db.rag_autosave_state.find_one({"_id": "last_run"})
        if state:
            since = state["last_run"]
            if hasattr(since, 'tzinfo') and since.tzinfo is not None:
                since = since.replace(tzinfo=None)
        else:
            since = datetime(2020, 1, 1)

    print(f"[{now}] RAG 자동저장 시작")
    print(f"마지막 저장 시각: {since}")

    all_conversations = list(db.conversations.find({}, {"conversationId": 1}))
    conv_id_list = [c.get("conversationId") for c in all_conversations if c.get("conversationId")]
    print(f"전체 대화 수: {len(conv_id_list)}")

    recent_messages = list(db.messages.find({
        "conversationId": {"$in": conv_id_list},
        "createdAt": {"$gt": since}
    }))
    print(f"새 메시지 {len(recent_messages)}개 발견")

    conv_ids = list(set([m["conversationId"] for m in recent_messages if "conversationId" in m]))
    print(f"대화 {len(conv_ids)}개 처리 중")

    success = 0
    fail = 0
    skip = 0

    for conv_id in conv_ids:
        messages = list(db.messages.find(
            {"conversationId": conv_id},
            sort=[("createdAt", 1)]
        ))
        if not messages:
            continue

        content = get_conversation_text(messages)
        if not content.strip():
            skip += 1
            continue

        file_id = str(uuid.uuid4())
        filename = f"conv_{conv_id[:8]}.txt"

        # 1. RAG API에 직접 저장
        status, response_text = save_to_rag(file_id, filename, content)
        print(f"대화 {conv_id[:8]}... → RAG 저장: {status} / {response_text}")

        if status != 200:
            fail += 1
            continue

        # 2. MongoDB files 컬렉션에 파일 레코드 추가
        db.files.update_one(
            {"file_id": file_id},
            {"$set": {
                "file_id": file_id,
                "user": USER_ID,
                "filename": filename,
                "filepath": f"openai/vectordb/{file_id}",
                "source": "vectordb",
                "type": "text/plain",
                "size": len(content.encode("utf-8")),
                "embedded": True,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow()
            }},
            upsert=True
        )

        # 3. agents 컬렉션에 file_id 직접 추가
        db.agents.update_one(
            {"id": AGENT_ID},
            {"$addToSet": {"tool_resources.file_search.file_ids": file_id}}
        )

        print(f"대화 {conv_id[:8]}... → MongoDB 등록 완료")
        success += 1
        time.sleep(1)

    print(f"[완료] 성공: {success} / 실패: {fail} / skip: {skip}")

    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": datetime.utcnow()}},
        upsert=True
    )
    client.close()

if __name__ == "__main__":
    main()
