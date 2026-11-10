"""환경변수 로딩. 모든 모듈은 여기서 settings 를 import 해서 쓴다."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_provider: Literal["openai", "anthropic"] = "openai"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # 지도 / 장소
    kakao_rest_api_key: str = ""
    kakao_js_api_key: str = ""
    kakao_mobility_api_key: str = ""
    tmap_app_key: str = ""

    # 데이터
    tour_api_key: str = ""
    naver_client_id: str = ""
    naver_client_secret: str = ""
    tavily_api_key: str = ""

    # 날씨
    openweather_api_key: str = ""
    kma_api_key: str = ""

    # API 서버
    # 프론트가 Cloud Run 을 직접 호출(SSE 는 Hosting rewrite 를 거치면 버퍼링됨)하므로 배포 도메인을 허용한다
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://odiro-where.web.app",
        "https://odiro-where.firebaseapp.com",
    ]

    # 경로
    cache_dir: Path = PROJECT_ROOT / "cache"
    vectorstore_dir: Path = PROJECT_ROOT / "data" / "vectorstore"
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"

    def missing_keys(self) -> list[str]:
        """비어 있는 API 키 이름 목록 (LLM 은 둘 중 하나만 있으면 됨)."""
        required = {
            "KAKAO_REST_API_KEY": self.kakao_rest_api_key,
            "KAKAO_MOBILITY_API_KEY": self.kakao_mobility_api_key,
            "TMAP_APP_KEY": self.tmap_app_key,
            "TOUR_API_KEY": self.tour_api_key,
            "NAVER_CLIENT_ID": self.naver_client_id,
            "NAVER_CLIENT_SECRET": self.naver_client_secret,
            "TAVILY_API_KEY": self.tavily_api_key,
            "OPENWEATHER_API_KEY": self.openweather_api_key,
        }
        missing = [k for k, v in required.items() if not v]
        if not (self.openai_api_key or self.anthropic_api_key):
            missing.append("OPENAI_API_KEY 또는 ANTHROPIC_API_KEY")
        return missing


settings = Settings()
