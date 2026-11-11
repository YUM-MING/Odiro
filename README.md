# Odiro (어디로)

AI 국내 여행·데이트 코스 플래너. 조건(지역·날짜·이동수단·분위기)을 고르면 LangGraph 에이전트가 RAG + 실시간 검색 + 지도 API로
**실존이 확인된** 장소만으로 코스를 짜서 채팅과 지도에 보여주고, 대화로 바로 고칠 수 있다. 기획은 [PLAN.md](PLAN.md).

**팀 문서 (먼저 읽기)**
- [docs/HANDOVER.md](docs/HANDOVER.md) — 인수인계 (주차 시작 전 필독)
- [docs/TEAM_ROLES.md](docs/TEAM_ROLES.md) — 주차별 역할·일정·체크리스트
- [docs/DATA_AND_API.md](docs/DATA_AND_API.md) — API 키 발급처, 데이터 목록·규모
- [docs/API_SCHEMA.md](docs/API_SCHEMA.md) — 프론트 ↔ 백엔드 API 계약 (SSE 포함)

- 백엔드: Python 3.12 / FastAPI / LangGraph / Chroma (`odiro/`)
- 프론트: React 19 + TypeScript (Vite) + Kakao Map JS (`frontend/`)
- 배포: 프론트 → Firebase Hosting, 백엔드 → Cloud Run (Docker). 서비스 https://odiro-where.web.app

## 로컬 실행

```powershell
# 1) 백엔드
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env        # 키 채우기 (팀 메신저 비공개 노트). TourAPI 는 Decoding 키!
python scripts/check_apis.py       # 10개 전부 OK 인지
pytest                             # 41 passed
uvicorn odiro.api.main:app --reload   # http://localhost:8000/docs

# 2) 프론트 (새 터미널)
cd frontend
npm install
npm run dev                        # http://localhost:5173 (/api 는 8000 으로 프록시)
#   백엔드 없이 UI 만 보려면: $env:VITE_MOCK="1"; npm run dev   (예시 코스로 동작)
```

벡터 DB(`data/vectorstore/`, 약 250MB)는 git 에 없다. 인수인계 문서의 Drive 링크에서 tgz 를 받아 `data/` 아래에 풀거나,
아래 데이터 파이프라인을 직접 돌린다 (키·시간·비용 필요).

## 코스 생성 (CLI / API)

```powershell
python -m odiro.agent.run "성수동" --moods 감성/조용한 사진맛집 --party 연인
python -m odiro.agent.run "가평" --mode trip --days 2 --transport car --moods 뷰맛집/일몰
python -m odiro.agent.run "인천 송도" --transport car --moods 아이동반 "실내(비오는날)" --edit "마지막 장소를 실내 놀이공간으로"
python -m odiro.agent.graph                     # Mermaid 다이어그램 (발표용)
python scripts/warm_demo_cache.py --date 2026-11-29   # 시연 시나리오 3개 사전 캐시 (시연 날짜로!)
```

- 파이프라인: `parse_intent → retrieve(RAG ∥ 웹 ∥ 날씨 ∥ 일출) → draft_course → verify_places(카카오 실존 검증) → optimize_route → enrich → compose_answer`
- 평균 25~45초. 같은 조건은 7일 캐시(`cache/tools`)라 두 번째부터 0.1초.
- API: `POST /api/course/start` → `GET /api/course/stream/{job}` (SSE 진행상태) / `POST /api/course/edit`. 상세 [docs/API_SCHEMA.md](docs/API_SCHEMA.md)

## 데이터 수집 → 라벨링 → 인덱스 (Phase 1)

```powershell
# 모두 재실행 안전(이미 받은 건 건너뜀). 기본 대상은 수도권(서울 11·인천 28·경기 41), 나머지 시도는 --all
python -m odiro.data.ingest.tour_api        # TourAPI 메타(전수) + 상세(개발계정 기능별 일 1,000건, 내일 다시 실행하면 이어서)
python -m odiro.data.ingest.naver_blog      # 네이버 블로그 (시군구 × 테마 11, 쿼리당 30건)
python -m odiro.data.ingest.naver_blog --start 31 --per-query 70   # 31~100위까지 추가 수집
python -m odiro.data.ingest.labeling        # gpt-4o-mini 분위기 태그 (문서 1만 건 ≈ 1달러)
python -m odiro.data.ingest.build_index     # Chroma 적재 (OpenAI 임베딩) → data/vectorstore
python -m odiro.data.ingest.build_index --stats
python -m odiro.tools.rag_search "성수동 조용한 카페 데이트"   # 검색 확인
```

산출물 위치·실측 규모는 [docs/DATA_AND_API.md](docs/DATA_AND_API.md) 2-1 표.

## 배포 (GCP 프로젝트 `odiro-where`)

**자동 배포 (권장)** — `main` 에 push 하면 GitHub Actions(`.github/workflows/deploy.yml`)가 백엔드·프론트를 배포한다. 켜려면 1회:

1. ✅ (완료, 11/04) `bash scripts/setup_ci.sh` → GitHub Secret `GCP_SA_KEY`, Variable `CI_ENABLED=true`. 새 GCP 프로젝트로 옮길 때만 다시 실행.
2. ✅ (완료, 11/11) 벡터 DB: `tar czf vectorstore.tgz -C data vectorstore` → `gs://odiro-where-data/vectorstore.tgz`, Variable `VECTORSTORE_GCS_URI`. **인덱스를 다시 만들면 tgz 를 다시 올려야** 배포에 반영된다 (서버 꺼진 상태에서 tar 할 것).
3. API 키: `python scripts/push_env_to_cloudrun.py` (gcloud 로그인 필요). `.env` 의 키를 Cloud Run 환경변수로 올린다. 키 바꿀 때마다 재실행.
4. Kakao 디벨로퍼스 → 앱 → 플랫폼 Web 에 `https://odiro-where.web.app`, `http://localhost:5173` 등록, 카카오맵 활성화 ON (JS 키 도메인 제한).

**수동 배포** (gcloud / firebase CLI 로그인 필요)

```bash
gcloud run deploy odiro-api --source . --region asia-northeast3 --project odiro-where \
  --min-instances 0 --max-instances 1 --memory 4Gi --timeout 120 --allow-unauthenticated   # 벡터 DB 675MB + 에이전트 → 2Gi 는 요청 중 OOM, 4Gi 필요
cd frontend && VITE_API_URL=https://odiro-api-80160454962.asia-northeast3.run.app npm run build \
  && firebase deploy --only hosting --project odiro-where
```

- 프론트는 SSE 때문에 Cloud Run 을 **직접** 호출한다 (`VITE_API_URL`). Hosting 의 `/api/**` rewrite 는 폴백용. 백엔드 CORS 는 `odiro/config.py` `cors_origins`.
- 시연 당일만 콜드스타트 방지로 `--min-instances 1` 을 켜고, 끝나면 반드시 0 (1로 두면 월 1~2만 원). 결제 계정에 월 5,000원 예산 알림.
- 시연 전날 `python scripts/warm_demo_cache.py --date <시연일>` 을 배포 환경과 같은 캐시에… 는 불가(컨테이너 무상태)하므로, 시연은 **로컬 백엔드 + 사전 캐시** 또는 Cloud Run 콜드스타트 후 한 번씩 미리 실행해 둔다.

## 폴더 구조

```
odiro/
├─ odiro/
│  ├─ config.py            # 환경변수 (settings)
│  ├─ api/main.py          # FastAPI (동기·비동기 SSE 엔드포인트) · api/schemas.py (프론트 계약)
│  ├─ agent/               # nodes.py(7 노드 + modify) · graph.py · run.py(실행기·CLI·캐시) · llm.py · state.py
│  ├─ tools/               # search_place · get_route · get_sun_times · get_weather · rag_search · summarize_reviews · _util(캐시)
│  └─ data/ingest/         # regions · common · tour_api · naver_blog · labeling · build_index
├─ frontend/src/           # App(랜딩) · Builder(조건) · Plan(플래너) · MapView(카카오맵) · Progress · api.ts · mock.ts
├─ scripts/                # check_apis · warm_demo_cache · setup_ci.sh
├─ tests/                  # 41개 (네트워크 없음)
├─ data/raw/, data/vectorstore/, cache/   # git 제외
├─ docs/                   # HANDOVER · TEAM_ROLES · DATA_AND_API · API_SCHEMA
├─ .github/workflows/deploy.yml
├─ Dockerfile
└─ PLAN.md
```
