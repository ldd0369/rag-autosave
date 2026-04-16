import os
import time
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
LIBRECHAT_TOKEN = os.environ.get("LIBRECHAT_TOKEN")
LIBRECHAT_URL = "https://librechat-production-8435.up.railway.app"
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

def upload_to_librechat(conv_id, lines, created_at):
    content = f"대화ID: {conv_id}\n날짜: {created_at}\n\n" + "\n".join(lines)
    filename = f"conv_{conv_id[:8]}.txt"
    response = requests.post(
        f"{LIBRECHAT_URL}/api/files",
        headers={"Authorization": f"Bearer {LIBRECHAT_TOKEN}"},
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        data={
            "endpoint": "agents",
            "agent_id": AGENT_ID,
            "tool_resource": "file_search"
        },
        timeout=60
    )
    return response.status_code, response.text[:200]

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
        status, response_text = upload_to_librechat(conv_id, lines, created_at)
        print(f"대화 {conv_id[:8]}... → 업로드: {status} / {response_text[:100]}")
        time.sleep(1)
    save_last_saved_time(now_ts)
    print(f"[{datetime.now()}] 완료")

if __name__ == "__main__":
    main()
