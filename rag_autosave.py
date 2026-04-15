import os
import time
import requests
from datetime import datetime, timezone
from pymongo import MongoClient

# 환경변수
MONGO_URI = os.environ.get("MONGO_URI")
RAG_API_URL = os.environ.get("RAG_API_URL", "https://rag-api-production-cc9c.up.railway.app")
LIBRECHAT_TOKEN = os.environ.get("LIBRECHAT_TOKEN")

# 마지막 저장 시각 추적 파일
LAST_SAVED_FILE = "/app/last_saved.txt"

def get_last_saved_time():
    try:
        with open(LAST_SAVED_FILE, "r") as f:
            return float(f.read().strip())
    except:
        # 처음 실행 시 1시간 전부터
        return time.time() - 3600

def save_last_saved_time(t):
    with open(LAST_SAVED_FILE, "w") as f:
        f.write(str(t))

def fetch_new_conversations(last_saved_ts):
    client = MongoClient(MONGO_URI)
    db = client.get_database("LibreChat")
    
    last_saved_dt = datetime.fromtimestamp(last_saved_ts, tz=timezone.utc)
    
    # LibreChat messages 컬렉션에서 최신 메시지 조회
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
    
    headers = {
        "Authorization": f"Bearer {LIBRECHAT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "documents": [
            {
                "page_content": content,
                "metadata": {
                    "source": f"librechat_conv_{conv_id}",
                    "type": "conversation"
                }
            }
        ]
    }
    
    response = requests.post(
        f"{RAG_API_URL}/documents",
        json=payload,
        headers=headers,
        timeout=30
    )
    
    return response.status_code

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
        status = save_to_rag(conv_id, lines, datetime.now().strftime("%Y-%m-%d %H:%M"))
        print(f"대화 {conv_id[:8]}... → RAG 저장 상태: {status}")
        time.sleep(0.5)  # API 과부하 방지
    
    save_last_saved_time(now_ts)
    print(f"[{datetime.now()}] 완료")

if __name__ == "__main__":
    main()
