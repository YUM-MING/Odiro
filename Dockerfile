# 백엔드(FastAPI + LangGraph) 이미지. Cloud Run 배포용.
# 프론트(React)는 frontend/ 에서 빌드해 Firebase Hosting 에 올린다.
#
# 벡터 DB(data/vectorstore, 약 250MB)는 git 에 없다. 로컬 빌드면 그대로 복사되고,
# GitHub Actions 는 GCS 에서 받아 data/vectorstore 에 풀어 둔 뒤 빌드한다 (.github/workflows/deploy.yml).
# API 키는 이미지에 넣지 않는다 → Cloud Run 환경변수.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 의존성 레이어 (코드보다 먼저 → 캐시 활용)
COPY pyproject.toml README.md ./
COPY odiro ./odiro
RUN pip install .

COPY scripts ./scripts
COPY data ./data
COPY cache ./cache

ENV PORT=8080
EXPOSE 8080
# 그래프·Chroma 로딩에 수 초 걸리므로 워커 1개, 타임아웃 넉넉히
CMD ["sh", "-c", "uvicorn odiro.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-keep-alive 75"]
