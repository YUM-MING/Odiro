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

## 2주차 — 에이전트 코어 + 나머지 시도 데이터 (팀원 A)

**데이터 분배**: 1주차가 수도권(서울·인천·경기)을 끝내고 넘긴다. 나머지 14개 시도(D6~D8)는 양이 커서 2주차 첫날에 1주차가 만든 스크립트를 **`--all` 옵션(수도권 제외)으로 백그라운드 실행**해 두고 에이전트 작업을 한다.

- [ ] Day 1: 인수인계 문서 읽고 로컬 세팅, `check_apis.py` 전부 OK 확인. `tour_api.py --all` / `naver_blog.py --all` 백그라운드 실행 (D6·D7, 하루 한도 안에서 며칠 걸림. 운영계정 승인되면 한도만 올라가고 키는 그대로)
- [ ] Day 2: Tools 구현 — `search_place`(Kakao Local), `get_route`(Mobility/Tmap + 직선거리 폴백), `get_sun_times`(astral), `get_weather`(OpenWeather)
- [ ] Day 3: `summarize_reviews`(Tavily + LLM), Tool 단위 테스트 `tests/test_tools.py`
- [ ] Day 4: LangGraph 노드 — `parse_intent → retrieve(RAG ∥ 웹) → draft_course(Structured Output)`
- [ ] Day 5: `verify_places`(실존 검증 루프 최대 2회) → `optimize_route`(≤6개 순열) → `enrich` → `compose_answer`
- [ ] Day 6: `modify_node` 수정 플라이휠. CLI `python -m odiro.agent.graph "성수동 뚜벅이 데이트"` 로 JSON 코스 출력. **할루시네이션 장소 0건** 확인
- [ ] Day 7: 나머지 시도 수집분 라벨링·인덱스 확장(D8, 예산 보고 샘플링). API 응답 JSON 스키마를 `docs/API_SCHEMA.md` 로 고정 (3주차 프론트용). 인수인계 문서 작성

산출물: `odiro/tools/*.py` 6개, `odiro/agent/nodes.py`, `tests/test_tools.py`, `docs/API_SCHEMA.md`, 전국 데이터 tgz (수도권 + 나머지 시도)

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

- **브랜치**: 별도 브랜치 없이 **`main` 에 바로 커밋·push** 한다 (주 1명 담당이라 충돌 없음). push 전에 `pytest` 와 `npm run build` 가 통과하는지만 확인. `main` 에 push 되면 자동 배포(설정되어 있으면) 또는 담당자가 수동 배포.
- **커밋 메시지**: 한국어 OK, 첫 줄에 뭘 했는지. 예: `Tool: get_route 구현 + 직선거리 폴백`
- **키·데이터 절대 커밋 금지**: `.env`, `data/raw`, `data/vectorstore`, `cache` 는 이미 gitignore.
- **막히면**: 하루 이상 막히는 건 팀 채팅에 바로 공유. 특히 API 승인 지연은 담당자가 아닌 사람도 신청 가능.
- **주 마지막 날**: `docs/HANDOVER.md` 에 본인 섹션을 추가하고 push 한 뒤 다음 담당자에게 알림.
