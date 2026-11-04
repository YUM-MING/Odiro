"""Odiro FastAPI 진입점. 실행: uvicorn odiro.api.main:app --reload

Phase 0: 헬스체크 + 환경 점검만.
Phase 2~3: POST /api/course (코스 생성), POST /api/course/edit (수정), GET /api/course/stream (SSE 진행상태)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from odiro import __version__
from odiro.config import settings

app = FastAPI(title="Odiro API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/api/config-check")
def config_check() -> dict:
    """어떤 API 키가 비어 있는지 (값은 절대 노출하지 않음)."""
    missing = settings.missing_keys()
    return {"ready": not missing, "missing": missing}


@app.get("/api/public-config")
def public_config() -> dict:
    """프론트에 내려줘도 되는 설정 (Kakao JS 키는 도메인 제한으로 보호됨)."""
    return {"kakao_js_api_key": settings.kakao_js_api_key}
