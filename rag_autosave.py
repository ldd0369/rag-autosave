# v9
import os
import time
import jwt
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.environ.get("MONGO_URI")
JWT_SECRET = os.environ.get("JWT_SECRET", "librechat2026")
LIBRECHAT_TOKEN = os.environ.get("LIBRECHAT_TOKEN", "")
FORCE_RESET = os.environ.get("FORCE_RESET", "false").lower() == "true"

LIBRECHAT_URL = "https://librechat-production-8435.up.railway.app"
USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

def generate_token():
    payload = {
        "id": USER_ID,
        "username": "admin",
        "provider": "local",
        "email": "",
        "name": "",
        "avatar": None,
        "role": "ADMIN",
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def get_auth_headers():
    if LIBRECHAT_TOKEN:
        return {"Authorization": f"Bearer {LIBRECHAT_TOKEN}"}
    return {"Authorization": f"Bearer {generate_token()}"}

def register_to_agent(filename, content):
    headers = get_auth_headers()
    time.sleep(3)
    files = {"file": (filename, content.encode("utf-8"), "text/plain")}
    data = {
        "endpoint": "agents",
        "agent_id": AGENT_ID,
        "tool_resource": "file_search"
    }
    response = requests.post(
        f"{LIBRECHAT_URL}/api/files",
        headers=headers,
        files=files,
        data=data,
        timeout=30
    )
    return response

def extract_text(content):
    """content 필드 형식에 관계없이 텍스트 추출"""
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
                # text, value, content 등 다양한 키 시도
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
        content = extract_text(msg.get("content", ""))
        if content.strip():
            lines.append(f"[{role}]: {content}")
    return "\n".join(lines)

def main():
    client = MongoClient(MONGO_URI)
    db = client.get_database("test")

    now_aware = datetime.now(timezone.utc)

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

    print(f"[{now_aware}] RAG 자동저장 시작")
    print(f"마지막 저장 시각: {since}")

    # 진단: 샘플 메시지 content 구조 확인
    sample_msg = db.messages.find_one({"conversationId": {"$exists": True}})
    if sample_msg:
        raw_content = sample_msg.get("content", "")
        print(f"[진단] content 타입: {type(raw_content).__name__}")
        print(f"[진단] content 값: {repr(raw_content)[:200]}")
        extracted = extract_text(raw_content)
        print(f"[진단] 추출 결과: {repr(extracted)[:200]}")

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

        filename = f"conv_{conv_id[:8]}.txt"

        try:
            agent_response = register_to_agent(filename, content)
            if agent_response.status_code == 200:
                print(f"대화 {conv_id[:8]}... → 에이전트 등록 완료")
                success += 1
            else:
                print(f"대화 {conv_id[:8]}... → 등록 실패: {agent_response.status_code}")
                if agent_response.status_code == 401:
                    print(f"[중단] 401 응답: {agent_response.text[:300]}")
                    break
                fail += 1
        except Exception as e:
            print(f"대화 {conv_id[:8]}... → 에러: {e}")
            fail += 1

    print(f"[완료] 성공: {success} / 실패: {fail} / 빈대화 skip: {skip}")

    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": datetime.utcnow()}},
        upsert=True
    )
    client.close()

if __name__ == "__main__":
    main()
