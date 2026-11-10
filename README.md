# Odiro (어디로)

AI 국내 여행·데이트 코스 플래너. 기획은 [PLAN.md](PLAN.md) 참고.

**팀 문서 (먼저 읽기)**
- [docs/HANDOVER.md](docs/HANDOVER.md) — 인수인계 (주차 시작 전 필독)
- [docs/TEAM_ROLES.md](docs/TEAM_ROLES.md) — 주차별 역할·일정·체크리스트
- [docs/DATA_AND_API.md](docs/DATA_AND_API.md) — 발급할 API 키, 모을 데이터 목록

- 백엔드: Python / FastAPI / LangGraph (`odiro/`)
- 프론트: React + TypeScript (Vite) + Kakao Map JS (`frontend/`)
- 배포: 프론트 → Firebase Hosting, 백엔드 → Cloud Run (Docker)
  - 서비스: https://odiro-where.web.app (`/api/**` 는 Cloud Run `odiro-api` 로 rewrite)

## 백엔드 시작

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env        # .env 에 키 채우기
python scripts/check_apis.py       # 키마다 OK / FAIL / SKIP
pytest
uvicorn odiro.api.main:app --reload   # http://localhost:8000/docs
```

## 데이터 수집 → 라벨링 → 인덱스 (Phase 1)

```powershell
# 모두 재실행 안전(이미 받은 건 건너뜀). 기본 대상은 수도권(서울 11·인천 28·경기 41), 2주차는 --all 로 나머지 시도.
python -m odiro.data.ingest.tour_api        # TourAPI 메타(전수) + 상세(개발계정 일 1,000건까지, 내일 다시 실행하면 이어서)
python -m odiro.data.ingest.naver_blog      # 네이버 블로그 (시군구 × 테마, 쿼리당 30건)
python -m odiro.data.ingest.labeling        # gpt-4o-mini 분위기 태그 (문서 1만 건 ≈ 1달러)
python -m odiro.data.ingest.build_index     # Chroma 적재 (OpenAI 임베딩) → data/vectorstore
python -m odiro.tools.rag_search "성수동 조용한 카페 데이트"   # 검색 확인
```

각 스크립트는 `--help` 로 옵션 확인. 산출물 위치·규모는 [docs/DATA_AND_API.md](docs/DATA_AND_API.md) 2-1 표 참고.

## 프론트 시작

```powershell
cd frontend
npm install
npm run dev                        # http://localhost:5173 (/api 는 8000 으로 프록시)
```

## 배포 (GCP 프로젝트 `odiro-where`)

```bash
# 백엔드 → Cloud Run (서울). 최소 0 / 최대 1 인스턴스라 요청 없으면 과금 0.
gcloud run deploy odiro-api --source . --region asia-northeast3 --project odiro-where \
  --min-instances 0 --max-instances 1 --memory 512Mi --allow-unauthenticated

# 환경변수(API 키)는 Cloud Run 콘솔 > 수정 > 변수 및 보안 비밀 에서 넣는다. (.env 는 이미지에 안 들어감)

# 프론트 → Firebase Hosting
cd frontend && npm run build && firebase deploy --only hosting --project odiro-where
```

- **자동 배포**: `bash scripts/setup_ci.sh` 를 1회 실행하면 이후 `main` push 시 GitHub Actions 가 위 두 배포를 대신 한다 (`.github/workflows/`). 켜기 전까지 push 는 사이트에 반영되지 않는다.

- 시연 당일만 콜드스타트 방지로 `--min-instances 1` 을 켜고, 끝나면 반드시 0으로 되돌린다 (1로 두면 월 1~2만 원).
- 결제 계정에 월 5,000원 예산 알림이 걸려 있다.

## 폴더 구조

```
trip/
├─ odiro/                 # 백엔드 패키지
│  ├─ config.py           # 환경변수 (settings)
│  ├─ api/main.py         # FastAPI 엔드포인트
│  ├─ agent/              # LangGraph 그래프·상태
│  ├─ tools/              # 자체 Tool 6개 (rag_search.py 구현됨, 나머지 2주차)
│  └─ data/ingest/        # regions(코드표) · common(유틸) · tour_api · naver_blog · labeling · build_index
├─ frontend/              # React 앱
│  ├─ src/api.ts          # 백엔드 호출
│  ├─ src/App.tsx
│  └─ firebase.json       # Firebase Hosting (+ /api → Cloud Run rewrite)
├─ docs/reference-landing.png  # 랜딩 디자인 레퍼런스
├─ data/raw/              # 수집 원본 (git 제외)
├─ data/vectorstore/      # Chroma (git 제외)
├─ cache/                 # API 응답 캐시 (git 제외)
├─ scripts/check_apis.py  # Phase 0 API 점검
├─ scripts/setup_ci.sh    # GitHub Actions 자동 배포 활성화 (1회)
├─ docs/                  # 인수인계·역할·데이터/API 문서
├─ tests/
├─ Dockerfile             # 백엔드 이미지
└─ PLAN.md
```
