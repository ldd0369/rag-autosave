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
JWT_SECRET = os.environ.get("JWT_SECRET", "librechat2026")
FORCE_RESET = os.environ.get("FORCE_RESET", "false").lower() == "true"

LIBRECHAT_URL = "https://librechat-production-8435.up.railway.app"
USER_ID = "69c9121e937a13bdcaf4e292"
AGENT_ID = "69ca1ffda677f261425029b4"

def generate_token():
    """JWT_SECRET으로 LibreChat 인증 토큰 직접 생성"""
    payload = {
        "id": USER_ID,
        "exp": int(time.time()) + 86400  # 24시간
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def upload_to_rag(content, filename):
    """RAG API에 직접 저장"""
    token = generate_token()
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": (filename, content.encode("utf-8"), "text/plain")}
    response = requests.post(
        f"{RAG_API_URL}/documents",
        headers=headers,
        files=files,
        timeout=30
    )
    return response

def register_to_agent(file_id, filename):
    """LibreChat API로 에이전트 파일 검색 등록"""
    token = generate_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3초 딜레이 (rate limit 방지)
    time.sleep(3)
    
    files = {"file": (filename, b"placeholder", "text/plain")}
    data = {
        "endpoint": "agents",
        "agent_id": AGENT_ID,
        "tool_resource": "file_search",
        "file_id": file_id
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
    """대화 메시지를 텍스트로 변환"""
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
    
    now = datetime.now(timezone.utc)
    
    # 마지막 저장 시각 확인
    if FORCE_RESET:
        since = now.replace(hour=0, minute=0, second=0) - __import__("datetime").timedelta(days=1)
        since = since.replace(tzinfo=timezone.utc)
    else:
        state = db.rag_autosave_state.find_one({"_id": "last_run"})
        if state:
            since = state["last_run"]
        else:
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            since = since.replace(tzinfo=timezone.utc)
    
    print(f"[{now}] RAG 자동저장 시작")
    print(f"마지막 저장 시각: {since}")
    
    # 새 메시지 있는 대화 조회
    user_obj_id = ObjectId(USER_ID)
    recent_messages = list(db.messages.find({
        "user": user_obj_id,
        "createdAt": {"$gt": since}
    }))
    
    print(f"새 메시지 {len(recent_messages)}개 발견")
    
    conv_ids = list(set([m["conversationId"] for m in recent_messages if "conversationId" in m]))
    print(f"대화 {len(conv_ids)}개 처리 중")
    
    for conv_id in conv_ids:
        messages = list(db.messages.find(
            {"conversationId": conv_id, "user": user_obj_id},
            sort=[("createdAt", 1)]
        ))
        
        if not messages:
            continue
        
        content = get_conversation_text(messages)
        if not content.strip():
            continue
        
        filename = f"conv_{conv_id[:8]}.txt"
        file_id = str(uuid.uuid4())
        
        # RAG API 직접 저장
        try:
            rag_response = upload_to_rag(content, filename)
            print(f"대화 {conv_id[:8]}... → RAG 저장 상태: {rag_response.status_code} / file_id: {file_id}")
        except Exception as e:
            print(f"대화 {conv_id[:8]}... → RAG 저장 실패: {e}")
            continue
        
        # 에이전트 등록
        try:
            agent_response = register_to_agent(file_id, filename)
            if agent_response.status_code == 200:
                print(f"에이전트 등록 완료: {file_id}")
            else:
                print(f"에이전트 등록 실패: {agent_response.status_code} / {agent_response.text[:200]}")
        except Exception as e:
            print(f"에이전트 등록 에러: {e}")
    
    # 마지막 실행 시각 업데이트
    db.rag_autosave_state.update_one(
        {"_id": "last_run"},
        {"$set": {"last_run": now}},
        upsert=True
    )
    
    print(f"[완료] 저장 정상 종료")
    client.close()

if __name__ == "__main__":
    main()
