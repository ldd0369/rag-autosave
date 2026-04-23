# update_instructions.py
# 실행: MONGO_URI=... python update_instructions.py              (dry-run, 현재 instructions 출력)
# 실행: MONGO_URI=... APPLY=true python update_instructions.py  (실제 적용)

import os
from pymongo import MongoClient

MONGO_URI = os.environ.get("MONGO_URI")
APPLY = os.environ.get("APPLY", "false").lower() == "true"
AGENT_ID = "agent_cTUjB6IrAnZ44EdmDB1i8"

NEW_TOOLS = [
    "naver_search",
    "daum_search",
    "youtube_search",
    "gdelt_search",
]

NEW_SECTION = """

=== 검색 도구 사용 규칙 (Phase 2 Level 2) ===

【도구 목록】
- web_search        : 기본 웹 검색 (Anthropic, 항상 사용 가능)
- naver_search      : 국내 뉴스/블로그/웹문서 (한국어 최적화)
- daum_search       : 국내 웹/블로그/카페 (Naver와 다른 인덱스)
- youtube_search    : YouTube 영상 검색 + 자막 추출
- gdelt_search      : 글로벌 언론 동향 (키 불필요, 항상 사용 가능)
- reddit_search     : Reddit 커뮤니티 반응 (키 있을 때만)
- perplexity_search : Perplexity Sonar Pro 심층 검색 (키 있을 때만)

【@태그 규칙】
사용자가 @태그를 명시하면 해당 도구를 반드시 사용할 것.

  @news   → naver_search(category=news) + daum_search(target=web) 병행 실행
  @intl   → gdelt_search + web_search(영어 쿼리, 해외 출처 우선)
  @gdelt  → gdelt_search(timespan=1m, sort=DateDesc)
  @yt     → youtube_search(extract_captions=true, max_results=5)
  @social → youtube_search + web_search(Instagram/TikTok 메타데이터)
  @verify → 최소 2개 이상 독립 출처로 교차 확인, 충돌 시 양쪽 모두 제시
  @rd     → reddit_search 사용 가능 시 실행, 없으면 web_search(site:reddit.com 쿼리) 대체
  @pp     → perplexity_search 사용 가능 시 실행, 없으면 web_search로 대체
  복수 태그 허용: 예) "삼성전자 실적 @news @verify"

【/명령어 규칙】
사용자가 /명령어를 사용하면 해당 모드를 강제 적용할 것.

  /quick  → web_search만 사용, 빠른 단일 검색
  /news   → naver_search + daum_search 집중, web_search 보조
  /intl   → gdelt_search + web_search(영어), 국내 소스 최소화
  /yt     → youtube_search(extract_captions=true) 우선
  /rd     → reddit_search 사용 가능 시 실행, 없으면 web_search(site:reddit.com 쿼리) 대체
  /pp     → perplexity_search 사용 가능 시 실행, 없으면 web_search로 대체
  /deep   → perplexity_search 사용 가능 시 + web_search 조합 최대 깊이, 없으면 web_search 단독 심층 검색
  /verify → @verify와 동일, 강제 교차 검증
  /gdelt  → gdelt_search 단독
  /social → youtube_search + web_search(소셜 메타데이터)
  /power  → 아직 준비 중입니다. /deep 또는 @verify로 대체 가능합니다.
  /help   → 이 목록을 사용자에게 출력

【출처 표시 규칙 - 모든 답변에 적용】
1. 출처 URL 반드시 표시 (없으면 "출처 불명" 명시)
2. 1차 출처 우선: 정부 발표 > 공시 > 주요 언론 > 블로그/SNS
3. 단일 출처일 경우 "(단일 출처)" 명시
4. 충돌하는 출처는 양쪽 다 제시하고 판단 보류
5. @verify 또는 /verify 시: 출처 신뢰도 등급 함께 표시

【자동 판단 기준】
- 최신 데이터 필요 → web_search 자동 실행
- 한국 뉴스/이슈 → naver_search 추가 고려
- 해외 미디어 반응 → gdelt_search 추가 고려
- 영상 콘텐츠 분석 → youtube_search 추가 고려
- @태그나 /명령어 없으면 Claude 자율 판단으로 도구 선택
"""


def main():
    if not MONGO_URI:
        print("[ERROR] MONGO_URI 환경변수가 설정되지 않았습니다.")
        print("  실행 방법: MONGO_URI='mongodb://...' python update_instructions.py")
        return

    client = MongoClient(MONGO_URI)
    db = client.get_database("test")

    agent = db.agents.find_one({"id": AGENT_ID})
    if not agent:
        print(f"[ERROR] 에이전트를 찾을 수 없음: {AGENT_ID}")
        client.close()
        return

    current = agent.get("instructions", "")
    current_tools = agent.get("tools", [])
    print(f"[현재 instructions]: {len(current)}자")
    print(f"[현재 tools]: {current_tools}")
    print()

    # 추가할 tool 계산 (중복 제외)
    tools_to_add = [t for t in NEW_TOOLS if t not in current_tools]
    new_tools = current_tools + tools_to_add

    already_done = "검색 도구 사용 규칙 (Phase 2 Level 2)" in current
    new_instructions = current if already_done else current + NEW_SECTION

    print(f"[예상 변경]")
    print(f"  instructions: {len(current)}자 → {len(new_instructions)}자"
          + (" (이미 적용됨)" if already_done else ""))
    print(f"  tools 추가: {tools_to_add if tools_to_add else '없음 (이미 등록됨)'}")
    print(f"  최종 tools: {new_tools}")
    print()

    if not APPLY:
        print("[DRY-RUN] 실제 수정 안 함.")
        print("  적용하려면: MONGO_URI='...' APPLY=true python update_instructions.py")
        client.close()
        return

    update_fields = {"tools": new_tools}
    if not already_done:
        update_fields["instructions"] = new_instructions

    result = db.agents.update_one({"id": AGENT_ID}, {"$set": update_fields})
    print(f"[업데이트 결과]")
    print(f"  matched_count  : {result.matched_count}")
    print(f"  modified_count : {result.modified_count}")

    updated = db.agents.find_one({"id": AGENT_ID})
    final_inst = updated.get("instructions", "")
    final_tools = updated.get("tools", [])
    inst_ok = "검색 도구 사용 규칙 (Phase 2 Level 2)" in final_inst
    tools_ok = all(t in final_tools for t in NEW_TOOLS)
    print(f"  instructions 검증: {'✅' if inst_ok else '❌'} ({len(final_inst)}자)")
    print(f"  tools 검증: {'✅' if tools_ok else '❌'} {final_tools}")

    client.close()


if __name__ == "__main__":
    main()
