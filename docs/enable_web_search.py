# enable_web_search.py
# 실행: python enable_web_search.py              (dry-run, 실제 수정 없음)
# 실행: APPLY=true python enable_web_search.py   (실제 적용)

import os
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
APPLY = os.environ.get("APPLY", "false").lower() == "true"
AGENT_ID = "agent_cTUjB6IrAnZ44EdmDB1i8"

def main():
    if not MONGO_URI:
        print("[ERROR] MONGO_URI 환경변수가 설정되지 않았습니다.")
        return

    client = MongoClient(MONGO_URI)
    db = client.get_database("test")

    # 1. 현재 상태 조회
    agent = db.agents.find_one({"id": AGENT_ID})
    if not agent:
        print(f"[ERROR] 에이전트를 찾을 수 없음: {AGENT_ID}")
        client.close()
        return

    current_params = agent.get("model_parameters", {})
    current_tools = agent.get("tools", [])

    print(f"[현재 상태]")
    print(f"  name           : {agent.get('name')}")
    print(f"  provider       : {agent.get('provider')}")
    print(f"  model          : {agent.get('model')}")
    print(f"  tools          : {current_tools}")
    print(f"  model_parameters:")
    for k, v in current_params.items():
        print(f"    {k}: {v}")
    print(f"  model_parameters.web_search: {current_params.get('web_search', '(없음)')}")
    print()

    if current_params.get("web_search") is True:
        print("[INFO] 이미 web_search: true 설정됨. 변경 불필요.")
        client.close()
        return

    # 2. 예상 결과 출력
    print("[예상 변경]")
    print(f"  model_parameters.web_search: {current_params.get('web_search', '(없음)')} → True")
    print()

    if not APPLY:
        print("[DRY-RUN] 실제 수정 안 함. 적용하려면: APPLY=true python enable_web_search.py")
        client.close()
        return

    # 3. 실제 업데이트
    result = db.agents.update_one(
        {"id": AGENT_ID},
        {"$set": {"model_parameters.web_search": True}}
    )
    print(f"[업데이트 결과]")
    print(f"  matched_count  : {result.matched_count}")
    print(f"  modified_count : {result.modified_count}")

    # 4. 검증 재조회
    updated = db.agents.find_one({"id": AGENT_ID})
    final_val = updated.get("model_parameters", {}).get("web_search")
    print(f"  최종 확인 model_parameters.web_search: {final_val}")

    if final_val is True:
        print("[완료] web_search 활성화 성공.")
    else:
        print("[WARNING] 업데이트 후에도 값이 True가 아님. 확인 필요.")

    client.close()

if __name__ == "__main__":
    main()
