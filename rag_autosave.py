# v8
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
    """LibreChat 소스코드 기준 정확한 JWT 형식"""
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
    """토큰 순서: LIBRECHAT_TOKEN 있으면 우선, 없으면 JWT 생성"""
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

def get_conversation_text(messages):
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join([c.get("text", "") for c in content if isinstance(c, dict)])
        if content:
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

    # 전체 conversations에서 대화 ID 수집
    all_conversations = list(db.conversations.find({}, {"conversationId": 1}))
    conv_id_list = [c.get("conversationId") for c in all_conversations if c.get("conversationId")]
    print(f"전체 대화 수: {len(conv_id_list)}")

    # since 이후 메시지가 있는 대화만 처리
    recent_messages = list(db.messages.find({
        "conversationId": {"$in": conv_id_list},
        "createdAt": {"$gt": since}
    }))

    print(f"새 메시지 {len(recent_messages)}개 발견")

    conv_ids = list(set([m["conversationId"] for m in recent_messages if "conversationId" in m]))
    print(f"대화 {len(conv_ids)}개 처리 중")

    success = 0
    fail = 0

    for conv_id in conv_ids:
        messages = list(db.messages.find(
            {"conversationId": conv_id},
            sort=[("createdAt", 1)]
        ))
        if not messages:
            continue

        content = get_conversation_text(messages)
        if not content.strip():
            continue

        filename = f"conv_{conv_id[:8]}.txt"

        try:
            agent_response = register_to_agent(filename, content)
            if agent_response.status_code == 200:
                print(f"대화 {conv_id[:8]}... → 에이전트 등록 완료")
                success += 1
            else:
                print(f"대화 {conv_id[:8]}... → 등록 실패: {agent_response.status_code}")
                fail += 1
                # 401이면 토큰 문제 — 첫 실패에서 바로 중단
                if agent_response.status_code == 401:
                    print(f"[중단] 401 Unauthorized — 토큰 문제. 응답: {agent_response.text[:300]}")
                    break
        except Exception as e:
            print(f"대화 {conv_id[:8]}... → 에러: {e}")
            fail += 1

    print(f"[완료] 성공: {success} / 실패: {fail}")

    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": datetime.utcnow()}},
        upsert=True
    )
    client.close()

if __name__ == "__main__":
    main()
