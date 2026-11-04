# 백엔드(FastAPI) 이미지. Cloud Run / Railway 등에 배포.
# 프론트(React)는 frontend/ 에서 빌드해 Firebase Hosting 에 올린다.
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml ./
COPY odiro ./odiro
RUN pip install --no-cache-dir .

COPY scripts ./scripts
COPY data ./data
COPY cache ./cache

ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn odiro.api.main:app --host 0.0.0.0 --port ${PORT}"]
