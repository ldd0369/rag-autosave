# v6
import os
import time
import jwt
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient
from bson import ObjectId

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

    # user 조건 없이 conversations 컬렉션에서 해당 유저 대화 ID 먼저 수집
    user_conversations = list(db.conversations.find(
        {"$or": [
            {"user": USER_ID},
            {"user": ObjectId(USER_ID)}
        ]},
        {"conversationId": 1}
    ))
    
    print(f"[진단] 유저 대화 수: {len(user_conversations)}")
    
    # 대화 ID 목록
    conv_id_list = [c["conversationId"] for c in user_conversations if "conversationId" in c]
    
    if not conv_id_list:
        # conversations 컬렉션 샘플 확인
        sample = db.conversations.find_one({})
        if sample:
            print(f"[진단] conversations 샘플 user 타입: {type(sample.get('user'))} / {repr(sample.get('user'))}")
        client.close()
        return

    # 해당 대화들의 최근 메시지 수집
    recent_messages = list(db.messages.find({
        "conversationId": {"$in": conv_id_list},
        "createdAt": {"$gt": since}
    }))

    print(f"새 메시지 {len(recent_messages)}개 발견")

    conv_ids = list(set([m["conversationId"] for m in recent_messages if "conversationId" in m]))
    print(f"대화 {len(conv_ids)}개 처리 중")

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
            else:
                print(f"대화 {conv_id[:8]}... → 등록 실패: {agent_response.status_code} / {agent_response.text[:200]}")
        except Exception as e:
            print(f"대화 {conv_id[:8]}... → 에러: {e}")

    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": datetime.utcnow()}},
        upsert=True
    )

    print(f"[완료] 저장 정상 종료")
    client.close()

if __name__ == "__main__":
    main()
