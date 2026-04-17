import os
import uuid
import time
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
FORCE_RESET = os.environ.get("FORCE_RESET", "false").lower() == "true"
RAG_API_URL = os.environ.get("RAG_API_URL", "http://rag-api.railway.internal:8000")
JWT_SECRET = os.environ.get("JWT_SECRET", "librechat2026")

USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

def get_jwt_token():
    import jwt
    payload = {
        "id": USER_ID,
        "exp": int(datetime.now(timezone.utc).timestamp()) + 86400
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def get_headers():
    token = get_jwt_token()
    return {"Authorization": f"Bearer {token}"}

def test_query():
    print("=== RAG 검색 테스트 ===")
    headers = get_headers()
    payload = {"query": "생일", "k": 3}
    try:
        response = requests.post(
            f"{RAG_API_URL}/query",
            json=payload,
            headers=headers,
            timeout=30
        )
        print(f"쿼리 상태: {response.status_code}")
        print(f"쿼리 결과: {response.text[:500]}")
    except Exception as e:
        print(f"쿼리 에러: {e}")
    print("=== 테스트 완료 ===")

def save_to_rag(file_id, filename, content):
    headers = get_headers()
    files_payload = {"file": (filename, content.encode("utf-8"), "text/plain")}
    data = {"file_id": file_id, "user": USER_ID}
    try:
        response = requests.post(
            f"{RAG_API_URL}/embed",
            headers=headers,
            files=files_payload,
            data=data,
            timeout=60
        )
        return response.status_code, response.text[:300]
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

    # RAG 검색 테스트
    test_query()

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

        status, response_text = save_to_rag(file_id, filename, content)
        print(f"대화 {conv_id[:8]}... → RAG: {status} / {response_text}")

        if status != 200:
            fail += 1
            continue

        db.agents.update_one(
            {"id": AGENT_ID},
            {"$addToSet": {"tool_resources.file_search.file_ids": file_id}}
        )
        print(f"대화 {conv_id[:8]}... → 완료")
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
