import os
import time
import uuid
import jwt
import requests
from datetime import datetime, timezone
from pymongo import MongoClient
from bson import ObjectId

MONGO_URI = os.environ.get("MONGO_URI")
RAG_API_URL = os.environ.get("RAG_API_URL", "http://rag-api.railway.internal:8000")
JWT_SECRET = os.environ.get("JWT_SECRET")
USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

LAST_SAVED_FILE = "/app/last_saved.txt"

def get_last_saved_time():
    if os.environ.get("FORCE_RESET") == "true":
        return time.time() - 86400
    try:
        with open(LAST_SAVED_FILE, "r") as f:
            return float(f.read().strip())
    except:
        return time.time() - 3600

def save_last_saved_time(t):
    with open(LAST_SAVED_FILE, "w") as f:
        f.write(str(t))

def fetch_new_conversations(last_saved_ts):
    client = MongoClient(MONGO_URI)
    db = client.get_database("test")
    last_saved_dt = datetime.fromtimestamp(last_saved_ts, tz=timezone.utc)
    messages = list(db.messages.find(
        {"createdAt": {"$gt": last_saved_dt}},
        {"_id": 0, "conversationId": 1, "text": 1, "sender": 1, "createdAt": 1}
    ).sort("createdAt", 1))
    client.close()
    return messages

def group_by_conversation(messages):
    conversations = {}
    for msg in messages:
        conv_id = str(msg.get("conversationId", "unknown"))
        if conv_id not in conversations:
            conversations[conv_id] = []
        sender = msg.get("sender", "unknown")
        text = msg.get("text", "")
        if text:
            conversations[conv_id].append(f"[{sender}]: {text}")
    return conversations

def save_to_rag(conv_id, lines, created_at):
    content = f"대화ID: {conv_id}\n날짜: {created_at}\n\n" + "\n".join(lines)
    file_id = str(uuid.uuid4())
    filename = f"conv_{conv_id[:8]}.txt"
    token = jwt.encode({"id": "rag-autosave"}, JWT_SECRET, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    files = {
        "file_id": (None, file_id),
        "file": (filename, content.encode("utf-8"), "text/plain"),
        "entity_id": (None, USER_ID)
    }
    response = requests.post(
        f"{RAG_API_URL}/embed",
        files=files,
        headers=headers,
        timeout=30
    )
    return response.status_code, file_id

def register_file_to_agent(file_id, filename, content):
    client = MongoClient(MONGO_URI)
    db = client.get_database("test")
    now = datetime.now(tz=timezone.utc)
    db.files.insert_one({
        "file_id": file_id,
        "filename": filename,
        "filepath": f"/app/uploads/temp/{USER_ID}/{filename}",
        "type": "text/plain",
        "size": len(content.encode("utf-8")),
        "user": USER_ID,
        "source": "vectordb",
        "embedded": True,
        "createdAt": now,
        "updatedAt": now
    })
    db.agents.update_one(
        {"_id": ObjectId(AGENT_ID)},
        {"$addToSet": {"file_ids": file_id}}
    )
    client.close()

def main():
    print(f"[{datetime.now()}] RAG 자동저장 시작")
    last_saved_ts = get_last_saved_time()
    now_ts = time.time()
    print(f"마지막 저장 시각: {datetime.fromtimestamp(last_saved_ts)}")
    messages = fetch_new_conversations(last_saved_ts)
    print(f"새 메시지 {len(messages)}개 발견")
    if not messages:
        print("저장할 내용 없음")
        save_last_saved_time(now_ts)
        return
    conversations = group_by_conversation(messages)
    print(f"대화 {len(conversations)}개 처리 중")
    for conv_id, lines in conversations.items():
        if not lines:
            continue
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        status, file_id = save_to_rag(conv_id, lines, created_at)
        print(f"대화 {conv_id[:8]}... → RAG 저장 상태: {status} / file_id: {file_id}")
        if status == 200:
            content = f"대화ID: {conv_id}\n날짜: {created_at}\n\n" + "\n".join(lines)
            filename = f"conv_{conv_id[:8]}.txt"
            register_file_to_agent(file_id, filename, content)
            print(f"에이전트 등록 완료: {file_id}")
        time.sleep(0.5)
    save_last_saved_time(now_ts)
    print(f"[{datetime.now()}] 완료")

if __name__ == "__main__":
    main()
