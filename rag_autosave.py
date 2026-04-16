# v4
import os
import time
import jwt
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
JWT_SECRET = os.environ.get("JWT_SECRET", "librechat2026")
FORCE_RESET = os.environ.get("FORCE_RESET", "false").lower() == "true"

LIBRECHAT_URL = "https://librechat-production-8435.up.railway.app"
USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

def generate_token():
    payload = {
        "id": USER_ID,
        "exp": int(time.time()) + 86400
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def register_to_agent(filename, content):
    token = generate_token()
    headers = {"Authorization": f"Bearer {token}"}
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
    now_naive = datetime.utcnow()  # MongoDB naive datetime과 비교용

    if FORCE_RESET:
        since = datetime(2020, 1, 1)  # naive
    else:
        state = db.rag_autosave_state.find_one({"_id": "last_run"})
        if state:
            since = state["last_run"]
            # aware면 naive로 변환
            if hasattr(since, 'tzinfo') and since.tzinfo is not None:
                since = since.replace(tzinfo=None)
        else:
            since = now_naive - timedelta(hours=24)

    print(f"[{now_aware}] RAG 자동저장 시작")
    print(f"마지막 저장 시각: {since}")

    # user: string, createdAt: naive datetime으로 쿼리
    recent_messages = list(db.messages.find({
        "user": USER_ID,
        "createdAt": {"$gt": since}
    }))

    print(f"새 메시지 {len(recent_messages)}개 발견")

    conv_ids = list(set([m["conversationId"] for m in recent_messages if "conversationId" in m]))
    print(f"대화 {len(conv_ids)}개 처리 중")

    for conv_id in conv_ids:
        messages = list(db.messages.find(
            {"user": USER_ID, "conversationId": conv_id},
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
            else:
                print(f"대화 {conv_id[:8]}... → 등록 실패: {agent_response.status_code} / {agent_response.text[:200]}")
        except Exception as e:
            print(f"대화 {conv_id[:8]}... → 에러: {e}")

    # 저장 시각은 naive로 저장
    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": now_naive}},
        upsert=True
    )

    print(f"[완료] 저장 정상 종료")
    client.close()

if __name__ == "__main__":
    main()
