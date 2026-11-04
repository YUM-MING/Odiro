# Odiro (어디로)

AI 국내 여행·데이트 코스 플래너. 기획은 [PLAN.md](PLAN.md) 참고.

- 백엔드: Python / FastAPI / LangGraph (`odiro/`)
- 프론트: React + TypeScript (Vite) + Kakao Map JS (`frontend/`)
- 배포: 프론트 → Firebase Hosting, 백엔드 → Cloud Run (Docker)

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

## 프론트 시작

```powershell
cd frontend
npm install
npm run dev                        # http://localhost:5173 (/api 는 8000 으로 프록시)
```

## 폴더 구조

```
trip/
├─ odiro/                 # 백엔드 패키지
│  ├─ config.py           # 환경변수 (settings)
│  ├─ api/main.py         # FastAPI 엔드포인트
│  ├─ agent/              # LangGraph 그래프·상태
│  ├─ tools/              # 자체 Tool 6개
│  └─ data/ingest/        # TourAPI·블로그 수집, 라벨링, 인덱싱
├─ frontend/              # React 앱
│  ├─ src/api.ts          # 백엔드 호출
│  ├─ src/App.tsx
│  └─ firebase.json       # Firebase Hosting (+ /api → Cloud Run rewrite)
├─ data/raw/              # 수집 원본 (git 제외)
├─ data/vectorstore/      # Chroma (git 제외)
├─ cache/                 # API 응답 캐시 (git 제외)
├─ scripts/check_apis.py  # Phase 0 API 점검
├─ tests/
├─ Dockerfile             # 백엔드 이미지
└─ PLAN.md
```
