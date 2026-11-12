# Odiro (어디로)

AI 국내 여행·데이트 코스 플래너. 조건(지역·날짜·이동수단·분위기)을 고르면 LangGraph 에이전트가 RAG + 실시간 검색 + 지도 API로
**실존이 확인된** 장소만으로 코스를 짜서 채팅과 지도에 보여주고, 대화로 바로 고칠 수 있다. 서비스 https://odiro-where.web.app

**팀 문서 (먼저 읽기)**
- [docs/HANDOVER.md](docs/HANDOVER.md) — 인수인계: 지금 상태, 매일 할 일, 남은 일 (주차 시작 전 필독)
- [docs/TEAM_ROLES.md](docs/TEAM_ROLES.md) — 주차별 역할·일정
- [docs/DATA_AND_API.md](docs/DATA_AND_API.md) — API 키 발급처, 데이터 목록·규모
- [docs/API_SCHEMA.md](docs/API_SCHEMA.md) — 프론트 ↔ 백엔드 API 계약 (SSE 포함)
- [PLAN.md](PLAN.md) — 기획서 (평가표 기준 설계)

**구성**
- 백엔드: Python 3.12 / FastAPI / LangGraph / Chroma (`odiro/`)
- 프론트: React 19 + TypeScript (Vite) + Kakao Map JS (`frontend/`)
- 배포: 프론트 → Firebase Hosting, 백엔드 → Cloud Run (Docker). `main` 에 push 하면 자동 배포

## 로컬 실행

```powershell
# 1) 백엔드
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env        # 키 채우기 (팀 메신저 비공개 노트의 완성본). TourAPI 는 일반 인증키(Decoding)
python scripts/check_apis.py       # 전부 OK 인지
pytest                             # 83 passed (네트워크 없음)
uvicorn odiro.api.main:app --reload   # http://localhost:8000/docs

# 2) 프론트 (새 터미널)
cd frontend
npm install
npm run dev                        # http://localhost:5173 (/api 는 8000 으로 프록시)
#   백엔드 없이 UI 만 보려면: $env:VITE_MOCK="1"; npm run dev   (예시 코스로 동작)
```

데이터(`data/raw`, `data/vectorstore` 약 740MB, `cache`)는 git 에 없다. 인수인계 문서 7번의 tgz 두 개를 받아 레포 루트에서 푼다.

```bash
tar xzf odiro-data-20261113.tgz            # data/raw + cache/ingest_state (수집 진행 상태)
tar xzf vectorstore-20261113.tgz -C data/  # data/vectorstore
```

## 코스 생성 (CLI / API)

```powershell
python -m odiro.agent.run "성수동" --moods 감성/조용한 사진맛집 --party 연인
python -m odiro.agent.run "가평" --mode trip --days 2 --transport car --moods 뷰맛집/일몰
python -m odiro.agent.run "인천 송도" --transport car --moods 아이동반 "실내(비오는날)" --edit "마지막 장소를 실내 놀이공간으로"
python -m odiro.agent.run "성수" --text "반지공방" --no-cache      # 자유 조건의 장소 종류는 반드시 한 곳 들어간다
python -m odiro.agent.graph                     # Mermaid 다이어그램 (발표용)
python scripts/warm_demo_cache.py --date 2026-11-29   # 시연 시나리오 3개 사전 캐시 (시연 날짜로!)
```

- 파이프라인: `parse_intent → retrieve(RAG ∥ 웹 ∥ 날씨 ∥ 일출 ∥ 주변 식당·카페·숙소) → draft_course → verify_places(카카오 실존 검증·보충) → optimize_route → enrich(리뷰·주차장) → compose_answer`
- 수정: `modify → verify_places → optimize_route → enrich → compose_answer` (바꾸는 자리만 다시 검증)
- 생성 50~90초, 수정 15~35초 (11/12 라이브 측정). 같은 조건은 7일 캐시(`cache/tools`)라 두 번째부터 즉시
- API: `POST /api/course/start` → `GET /api/course/stream/{job}` (SSE 진행 상태) / `POST /api/course/edit/start`. 상세 [docs/API_SCHEMA.md](docs/API_SCHEMA.md)
- 에이전트가 지키는 규칙(프랜차이즈 제외, 비 예보 실내 전환, 숙소·식사 배치 등)은 `odiro/agent/nodes.py` 와 `tests/test_agent_nodes.py` 가 기준

## 데이터 수집 → 라벨링 → 인덱스

**매일 한 번** (TourAPI 상세는 키마다 일 1,000건이라 날마다 이어서 받는다):

```bash
python scripts/daily_ingest.py            # 서울 → 인천 → 경기 → 나머지 시도 순으로 수집 → 라벨링 → 인덱스
python scripts/daily_ingest.py --status   # 시도별 진행 현황
```

개별 단계 (모두 재실행 안전. 기본 대상은 수도권 서울 11 · 인천 28 · 경기 41, 나머지 시도는 `--all`, 특정 시도는 `--area 코드…`):

```powershell
python -m odiro.data.ingest.tour_api        # 장소 메타(전수) + 상세(한도까지). --no-meta / --no-detail / --types / --daily-limit
python -m odiro.data.ingest.naver_blog      # 네이버 블로그 (시군구 × 테마 11, 쿼리당 30건). --start 31 --per-query 70 으로 추가 수집
python -m odiro.data.ingest.labeling        # gpt-4o-mini 분위기 태그 (문서 1만 건 ≈ 1달러). --only place|blog
python -m odiro.data.ingest.build_index     # Chroma 적재 (OpenAI 임베딩) → data/vectorstore. --stats 로 현황
python -m odiro.tools.rag_search "성수동 조용한 카페 데이트"   # 검색 확인
```

TourAPI 키를 여러 개 쓰려면 `.env` 에 `TOUR_API_KEYS_EXTRA=키2,키3` (쉼표 구분). 기본 키 한도가 차면 순서대로 이어 쓴다.
산출물 위치·실측 규모는 [docs/DATA_AND_API.md](docs/DATA_AND_API.md) 2-1 표.

## 배포 (GCP 프로젝트 `odiro-where`)

**자동 배포** — `main` 에 push 하면 GitHub Actions(`.github/workflows/deploy.yml`)가 백엔드(Cloud Run)와 프론트(Firebase Hosting)를 배포한다. 약 12분.
아래는 전부 설정이 끝난 상태이고, 바뀔 때만 다시 한다.

| 무엇 | 언제 다시 하나 | 방법 |
|---|---|---|
| GitHub Secret `GCP_SA_KEY`, Variable `CI_ENABLED` | GCP 프로젝트를 옮길 때 | Cloud Shell 에서 `bash scripts/setup_ci.sh` |
| 벡터 DB | 인덱스를 다시 만들었을 때 | 서버를 끄고 `tar czf vectorstore.tgz -C data vectorstore` → `gcloud storage cp vectorstore.tgz gs://odiro-where-data/vectorstore.tgz` → 배포 한 번 |
| Cloud Run API 키 | `.env` 의 키를 바꿨을 때 | `python scripts/push_env_to_cloudrun.py` (gcloud 로그인 필요) |
| 카카오 지도 도메인 | 도메인이 바뀔 때 | 카카오 디벨로퍼스 → 앱 → **JavaScript SDK 도메인** 에 등록, 카카오맵 활성화 ON |

**수동 배포** (gcloud / firebase CLI 로그인 필요)

```bash
gcloud run deploy odiro-api --source . --region asia-northeast3 --project odiro-where \
  --min-instances 0 --max-instances 1 --memory 4Gi --cpu 1 --timeout 120 --allow-unauthenticated
cd frontend && VITE_API_URL=https://odiro-api-80160454962.asia-northeast3.run.app npm run build \
  && firebase deploy --only hosting --project odiro-where
```

- 메모리는 **4Gi**. 2Gi 에서는 코스 생성 중 메모리 초과로 인스턴스가 죽었다. 인덱스가 커지면 다시 확인한다 (`gcloud logging read 'resource.labels.service_name="odiro-api" AND severity>=WARNING' --limit 20`)
- 프론트는 SSE 때문에 Cloud Run 을 **직접** 호출한다 (`VITE_API_URL`). Hosting 의 `/api/**` rewrite 는 폴백용. 백엔드 CORS 는 `odiro/config.py` `cors_origins`
- 최소 인스턴스는 0 유지. 시연 당일만 `--min-instances 1` 로 콜드스타트를 막고 끝나면 반드시 0 (1 로 두면 월 1~2만 원). 결제 계정에 월 5,000원 예산 알림이 걸려 있다
- Cloud Run 컨테이너는 상태가 없어 캐시가 유지되지 않는다. 시연은 **로컬 백엔드 + 사전 캐시**(`warm_demo_cache.py`) 또는 배포 사이트에서 시나리오를 한 번씩 미리 돌려 둔다

## 폴더 구조

```
odiro/
├─ odiro/
│  ├─ config.py            # 환경변수 (settings)
│  ├─ api/main.py          # FastAPI (동기·비동기 SSE 엔드포인트) · api/schemas.py (프론트 계약)
│  ├─ agent/               # nodes.py(노드·규칙) · graph.py · run.py(실행기·CLI·캐시) · llm.py · state.py(상태 스키마)
│  ├─ tools/               # search_place · get_route · get_sun_times · get_weather · rag_search · summarize_reviews · _util(캐시)
│  └─ data/ingest/         # regions · common · tour_api · naver_blog · labeling · build_index
├─ frontend/src/           # App(랜딩) · Builder(조건) · Plan(플래너) · MapView(카카오맵) · Progress · mapUtil · markdown · api.ts · mock.ts
├─ scripts/                # daily_ingest · check_apis · warm_demo_cache · push_env_to_cloudrun · setup_ci.sh
├─ tests/                  # 83개 (네트워크 없음)
├─ data/raw/, data/vectorstore/, cache/   # git 제외
├─ docs/                   # HANDOVER · TEAM_ROLES · DATA_AND_API · API_SCHEMA
├─ .github/workflows/deploy.yml
├─ Dockerfile
└─ PLAN.md
```
