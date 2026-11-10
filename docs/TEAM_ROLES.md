# 팀 역할 분담 (3명 · 주 1명 릴레이)

> 한 주에 한 명이 메인 담당. 끝나면 [HANDOVER.md](HANDOVER.md) 양식으로 다음 사람에게 인수인계.
> 날짜는 2026-11-04 시작 기준. 팀 일정에 맞춰 조정.

| 주차 | 기간 | 담당 | 핵심 목표 (끝나면 "돌아가는 것") | PLAN.md Phase |
|---|---|---|---|---|
| 0주차 | ~11/04 | Claude (세팅·배포) | 레포·배포·랜딩 페이지 완료 | Phase 0 |
| **1주차** | 11/04 ~ 11/10 | **YUM-MING** | API 키 전부 발급 + **수도권(서울·인천·경기)** 데이터 → `rag_search` 가 그럴듯한 문서를 돌려줌 | Phase 1 |
| **2주차** | 11/11 ~ 11/17 | 팀원 A | Tool 6개 + LangGraph → 터미널에서 코스 JSON 생성 성공 (+ 나머지 14개 시도 데이터 수집 백그라운드) | Phase 2 (+ Phase 1 전국분) |
| **3주차** | 11/18 ~ 11/24 | 팀원 B | 프론트 연결 → 웹에서 전 과정 시연 + 캐시·폴백 + 시연 영상 | Phase 3·4 |
| 발표 준비 | 11/25 ~ | 전원 | 슬라이드·리허설 2회 (네트워크 끊고 1회) | Phase 5 |

## 1주차 — 데이터 기초 + 키 발급 (YUM-MING) · 담당 지역: 서울·인천·경기

**왜 이 순서인가**: API 키 발급(특히 TourAPI 운영계정 승인)이 제일 오래 걸리고, 데이터가 있어야 2주차가 에이전트를 테스트할 수 있다.

**지역 분담**: 서비스 목표는 전국. 1주차는 수도권(서울 areaCode 1 · 인천 2 · 경기 31)을 메타 전수 + 상세·블로그·태그까지 끝내고, 나머지 14개 시도는 2주차가 같은 스크립트로 이어받는다. 그래서 모든 수집 스크립트는 **지역을 인자로 받아야 한다** (`--area 1 2 31`, `--all`).

- [ ] **Day 1**: TourAPI **개발계정** 활용신청 (자동승인, 기능별 일 1,000건). 운영계정은 호출 이력이 없으면 반려되므로 수집으로 이력을 쌓은 뒤 주 후반에 전환 신청. Kakao·네이버·OpenAI 키 발급. `python scripts/check_apis.py` 에서 최소 Kakao Local·네이버·OpenAI `OK`
- [ ] Day 2: `odiro/data/ingest/tour_api.py` — 시도·콘텐츠타입별 `areaBasedList2` 페이지네이션 수집 (`numOfRows=1000`). 서울·인천·경기 메타 전수 (D1). 상세(`detailCommon2`)는 한도 안에서 우선순위 상위부터 (D2)
- [ ] Day 3: `naver_blog.py` — "시군구 + 테마" 쿼리로 블로그 글 수집 (수도권 66개 시군구, 쿼리당 상위 30건 샘플링), 광고성 1차 필터 (D3)
- [ ] Day 4: `labeling.py` — gpt-4o-mini 로 분위기 태그 라벨링, Structured Output 으로 JSON 강제 (D4)
- [ ] Day 5: `build_index.py` — Chroma 적재 (메타데이터: 지역·태그·카테고리·출처 URL), `odiro/tools/rag_search.py` 1차 구현 (D5)
- [ ] Day 6: Tmap·Kakao Mobility·Tavily·OpenWeather 키까지 발급해 `check_apis.py` **전부 OK**. Cloud Run 환경변수에 키 등록
- [ ] Day 7: TourAPI **운영계정 전환 신청** (호출 이력 쌓인 뒤). 데이터 tgz 를 Drive 에 올리고 **인수인계 문서 작성**

산출물: `odiro/data/ingest/*.py` 4개, `odiro/tools/rag_search.py`, 수도권 `data/` tgz 링크, `.env` 완성본(비공개 공유)

> **11/11 역할 재조정**: 1주차가 Phase 1 에 더해 Phase 2(Tool 6개·LangGraph·CLI)·Phase 3(API·프론트 플래너) 1차 구현까지 끝냈다
> (HANDOVER.md 1주차 섹션). 아래 2·3주차 계획은 "만들기" 에서 "전국 확장·품질·안정화·시연" 으로 바꿨다. 원래 계획은 git 이력(`6cd88f6`) 참고.

## 2주차 — 전국 데이터 확장 + 에이전트 품질 (팀원 A)

**데이터 분배**: 수도권(서울·인천·경기)은 끝났다. 나머지 14개 시도(D6~D8)를 `--all` 로 백그라운드 수집하면서 에이전트 품질을 올린다.

- [ ] Day 1: 인수인계 문서 읽고 로컬 세팅 (`pytest`, `check_apis.py`, `python -m odiro.agent.run "성수동"`, 프론트 `/plan`). **배포 활성화 4가지**(README 배포 1~4) 해서 사이트에서 코스가 나오게. `tour_api --all` / `naver_blog --all` 백그라운드 시작, 운영계정 전환 신청
- [ ] Day 2: 자차 반경·동 단위 요청 처리 (`VERIFY_RADIUS`, 지오코딩) + 체류 시간·식사 시간대 규칙 → `nodes.DRAFT_SYSTEM` 프롬프트 개선. 결과를 시나리오 3개로 전후 비교
- [ ] Day 3: 리뷰 요약 공란 비율 줄이기 (`summarize_reviews` 쿼리·발췌 수), 여행 모드 숙소 배치 규칙, `tests/test_tools.py` 보강
- [ ] Day 4: 응답 시간 30~45초 → 25초 목표: draft/compose 모델 분리(`LLM_MODEL_DRAFT`), compose 스트리밍 또는 템플릿 우선 표시. 노드별 ms 는 `meta.trace` 로 측정
- [ ] Day 5: 나머지 시도 라벨링·인덱싱(`labeling --all`, `build_index --all`, 예산 보고 샘플링) + `rag_search.OTHER_REGION_WORDS`·`_SIDO_ALIASES` 전국 보강
- [ ] Day 6: 할루시네이션 0건 검증 스크립트 (시나리오 10개 돌려 `verified` 아닌 장소가 응답에 없는지, 반경 밖 장소 비율) → `tests/` 또는 `scripts/eval_courses.py`
- [ ] Day 7: 전국 데이터 tgz 업로드, 인수인계 문서 작성

산출물: 전국 인덱스, 프롬프트·검증 개선 커밋, 평가 스크립트, `.env`/tgz 공유

## 3주차 — UI 다듬기 + 안정화 + 시연 (팀원 B)

- [ ] Day 1: 실브라우저에서 전 흐름 점검 (조건 빌더 → SSE 진행 → 지도 핀·동선·팝업 → 바꾸기 → 공유). 모바일 레이아웃. 버그 목록 → 수정
- [ ] Day 2: 핀 클릭 팝업 내용(영업시간·전화·이미지), 장소 카드 ↔ 지도 연동, 빠른 수정 버튼 문구 다듬기, 에러·타임아웃 UX
- [ ] Day 3: 안정화 — 사이트에서 20회 연속 생성해 실패율 측정, Cloud Run 메모리/타임아웃 조정, 콜드스타트 체감 개선(로딩 메시지)
- [ ] Day 4: 시연 시나리오 3개 사전 캐시 (`scripts/warm_demo_cache.py --date <시연일>`), 네트워크 끊고 리허설 (로컬 백엔드 + 캐시)
- [ ] Day 5: 인트로 애니메이션 + BGM (핵심 루프가 안정적일 때만). 그래프 다이어그램 PNG (`python -m odiro.agent.graph` → mermaid.live)
- [ ] Day 6: **시연 영상 녹화**, 스크린샷 백업, 발표 슬라이드용 로그 패널 캡처("RAG 16건 / 웹 7건 참조")
- [ ] Day 7: 배포 최종본 태그, 코드 동결, 인수인계(발표 준비용) 문서

산출물: 배포 URL 에서 전 과정 동작, 시연 영상, `cache/demo/`, 실패율 리포트

## 공통 규칙

- **브랜치**: 별도 브랜치 없이 **`main` 에 바로 커밋·push** 한다 (주 1명 담당이라 충돌 없음). push 전에 `pytest` 와 `npm run build` 가 통과하는지만 확인. `main` 에 push 되면 자동 배포(설정되어 있으면) 또는 담당자가 수동 배포.
- **커밋 메시지**: 한국어 OK, 첫 줄에 뭘 했는지. 예: `Tool: get_route 구현 + 직선거리 폴백`
- **키·데이터 절대 커밋 금지**: `.env`, `data/raw`, `data/vectorstore`, `cache` 는 이미 gitignore.
- **막히면**: 하루 이상 막히는 건 팀 채팅에 바로 공유. 특히 API 승인 지연은 담당자가 아닌 사람도 신청 가능.
- **주 마지막 날**: `docs/HANDOVER.md` 에 본인 섹션을 추가하고 push 한 뒤 다음 담당자에게 알림.
