# Odiro (어디로)

AI 국내 여행·데이트 코스 플래너. 기획은 [PLAN.md](PLAN.md) 참고.

## 시작하기

```powershell
# 1. 가상환경
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. 설치
pip install -e ".[dev]"

# 3. 환경변수
Copy-Item .env.example .env   # 그리고 .env 에 키 채우기

# 4. API 점검 (키마다 OK / FAIL / SKIP)
python scripts/check_apis.py

# 5. 테스트
pytest

# 6. 앱 실행
streamlit run odiro/app/main.py
```

## 폴더 구조

```
trip/
├─ odiro/
│  ├─ config.py          # 환경변수 (settings)
│  ├─ app/main.py        # Streamlit UI
│  ├─ agent/             # LangGraph 그래프·상태
│  ├─ tools/             # 자체 Tool 6개
│  └─ data/ingest/       # TourAPI·블로그 수집, 라벨링, 인덱싱
├─ data/raw/             # 수집 원본 (git 제외)
├─ data/vectorstore/     # Chroma (git 제외)
├─ cache/                # API 응답 캐시 (git 제외)
├─ scripts/check_apis.py # Phase 0 API 점검
├─ tests/
├─ Dockerfile
└─ PLAN.md
```
