# 팀 역할 분담 (3명 · 주 1명 릴레이)

> 한 주에 한 명이 메인 담당. 끝나면 [HANDOVER.md](HANDOVER.md) 양식으로 다음 사람에게 인수인계.
> 날짜는 2026-11-04 시작 기준. 팀 일정에 맞춰 조정.

| 주차 | 기간 | 담당 | 핵심 목표 (끝나면 "돌아가는 것") | PLAN.md Phase |
|---|---|---|---|---|
| 0주차 | ~11/04 | Claude (세팅·배포) | 레포·배포·랜딩 페이지 완료 | Phase 0 |
| **1주차** | 11/04 ~ 11/10 | **YUM-MING** | API 키 전부 발급 + 시연 지역 3곳 데이터 → `rag_search` 가 그럴듯한 문서를 돌려줌 | Phase 1 |
| **2주차** | 11/11 ~ 11/17 | 팀원 A | Tool 6개 + LangGraph → 터미널에서 코스 JSON 생성 성공 (+ 전국 데이터 수집 백그라운드) | Phase 2 (+ Phase 1 전국분) |
| **3주차** | 11/18 ~ 11/24 | 팀원 B | 프론트 연결 → 웹에서 전 과정 시연 + 캐시·폴백 + 시연 영상 | Phase 3·4 |
| 발표 준비 | 11/25 ~ | 전원 | 슬라이드·리허설 2회 (네트워크 끊고 1회) | Phase 5 |

## 1주차 — 데이터 기초 + 키 발급 (YUM-MING)

**왜 이 순서인가**: API 키 발급(특히 TourAPI 운영계정 승인)이 제일 오래 걸리고, 데이터가 있어야 2주차가 에이전트를 테스트할 수 있다.

- [ ] **Day 1 (오늘)**: TourAPI 활용신청 + 운영계정 증량 신청 (승인 대기 시작). Kakao·네이버·OpenAI 키 발급. `python scripts/check_apis.py` 에서 최소 Kakao Local·네이버·OpenAI `OK`
- [ ] Day 2: `odiro/data/ingest/tour_api.py` — 지역코드·콘텐츠타입별 `areaBasedList2` 페이지네이션 수집. 성수(서울 성동구)·강릉·전주 먼저 (D1)
- [ ] Day 3: `naver_blog.py` — "지역 + 테마" 쿼리로 블로그 글 수집, 광고성 1차 필터 (D3)
- [ ] Day 4: `labeling.py` — gpt-4o-mini 로 분위기 태그 라벨링, Structured Output 으로 JSON 강제 (D4)
- [ ] Day 5: `build_index.py` — Chroma 적재 (메타데이터: 지역·태그·카테고리·출처 URL), `odiro/tools/rag_search.py` 1차 구현 (D5)
- [ ] Day 6: Tmap·Kakao Mobility·Tavily·OpenWeather 키까지 발급해 `check_apis.py` **전부 OK**. Cloud Run 환경변수에 키 등록
- [ ] Day 7: 데이터 tgz 를 Drive 에 올리고 **인수인계 문서 작성**

산출물: `odiro/data/ingest/*.py` 4개, `odiro/tools/rag_search.py`, `data/` tgz 링크, `.env` 완성본(비공개 공유)

## 2주차 — 에이전트 코어 + 전국 데이터 (팀원 A)

**데이터 분배**: 전국 수집(D6~D8)은 양이 커서 1주차에 다 맡기지 않는다. 2주차 첫날에 1주차가 만든 스크립트를 **전국 옵션으로 백그라운드 실행**해 두고 에이전트 작업을 한다.

- [ ] Day 1: 인수인계 문서 읽고 로컬 세팅, `check_apis.py` 전부 OK 확인. `tour_api.py --all` / `naver_blog.py --all` 백그라운드 실행 (D6·D7, 하루 한도 안에서 며칠 걸림)
- [ ] Day 2: Tools 구현 — `search_place`(Kakao Local), `get_route`(Mobility/Tmap + 직선거리 폴백), `get_sun_times`(astral), `get_weather`(OpenWeather)
- [ ] Day 3: `summarize_reviews`(Tavily + LLM), Tool 단위 테스트 `tests/test_tools.py`
- [ ] Day 4: LangGraph 노드 — `parse_intent → retrieve(RAG ∥ 웹) → draft_course(Structured Output)`
- [ ] Day 5: `verify_places`(실존 검증 루프 최대 2회) → `optimize_route`(≤6개 순열) → `enrich` → `compose_answer`
- [ ] Day 6: `modify_node` 수정 플라이휠. CLI `python -m odiro.agent.graph "성수동 뚜벅이 데이트"` 로 JSON 코스 출력. **할루시네이션 장소 0건** 확인
- [ ] Day 7: 전국 수집분 라벨링·인덱스 확장(D8, 예산 보고 샘플링). API 응답 JSON 스키마를 `docs/API_SCHEMA.md` 로 고정 (3주차 프론트용). 인수인계 문서 작성

산출물: `odiro/tools/*.py` 6개, `odiro/agent/nodes.py`, `tests/test_tools.py`, `docs/API_SCHEMA.md`, 전국 데이터 tgz

## 3주차 — UI 연결 + 안정화 + 시연 (팀원 B)

- [ ] Day 1: FastAPI `POST /api/course`, `POST /api/course/edit`, `GET /api/course/stream`(SSE 노드 진행상태)
- [ ] Day 2: 프론트 조건 빌더 (랜딩의 검색 카드 → 모드·이동수단·지역·날짜·예산·분위기 태그·자유 텍스트)
- [ ] Day 3: 채팅 + Kakao Map JS 스플릿 뷰 — 번호 핀, 동선 폴리라인, 핀 클릭 팝업
- [ ] Day 4: 빠른 수정 버튼(플라이휠), 사이드바 노드 진행 표시, 공유(텍스트 복사·카카오맵 링크)
- [ ] Day 5: 안정화 — 타임아웃·폴백·diskcache, 시연 시나리오 3개 사전 실행 캐시 (D9). 날씨 실내 전환
- [ ] Day 6: 인트로 애니메이션 + BGM (핵심 루프 완성 후에만). 벡터 DB 배포 방식 결정 (이미지 포함 vs GCS)
- [ ] Day 7: 배포 최종본, **시연 영상 녹화**, 인수인계(발표 준비용) 문서

산출물: 배포 URL 에서 전 과정 동작, 시연 영상, `cache/demo/`

## 공통 규칙

- **브랜치**: 각자 `week1/…`, `week2/…` 브랜치에서 작업 → PR → 본인이 merge (리뷰는 선택). `main` 에 merge 되면 자동 배포(설정되어 있으면) 또는 담당자가 수동 배포.
- **커밋 메시지**: 한국어 OK, 첫 줄에 뭘 했는지. 예: `Tool: get_route 구현 + 직선거리 폴백`
- **키·데이터 절대 커밋 금지**: `.env`, `data/raw`, `data/vectorstore`, `cache` 는 이미 gitignore.
- **막히면**: 하루 이상 막히는 건 팀 채팅에 바로 공유. 특히 API 승인 지연은 담당자가 아닌 사람도 신청 가능.
- **주 마지막 날**: `docs/HANDOVER.md` 에 본인 섹션을 추가하고 push 한 뒤 다음 담당자에게 알림.
