"""LangGraph 상태 정의. PLAN.md 5-3 참고."""

from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class Place(BaseModel):
    """코스에 들어가는 장소 하나. verified=True 인 것만 지도에 올린다."""

    name: str
    category: str = ""  # 식당 / 카페 / 관광지 / 놀거리 ...
    lat: float | None = None
    lng: float | None = None
    address: str = ""
    kakao_place_id: str = ""
    place_url: str = ""
    reason: str = ""  # LLM 이 쓴 추천 이유
    tags: list[str] = Field(default_factory=list)  # 분위기 태그
    verified: bool = False
    day: int = 1  # 여행 모드에서 Day 번호
    order: int = 0  # 하루 안에서의 방문 순서


class Leg(BaseModel):
    """장소 간 이동 구간."""

    from_idx: int
    to_idx: int
    transport: Literal["walk", "transit", "car"]
    duration_min: int
    distance_m: int
    polyline: list[tuple[float, float]] = Field(default_factory=list)  # (lat, lng)
    estimated: bool = False  # API 실패 시 직선거리 추정이면 True


class EditRequest(BaseModel):
    """'두 번째 카페 바꿔줘' 류의 수정 요청."""

    target_order: int
    target_day: int = 1
    instruction: str


class CourseState(TypedDict, total=False):
    # 입력 조건 (GUI + 자연어)
    mode: Literal["outing", "trip"]
    transport: Literal["walk", "car"]
    region: str
    date: str  # YYYY-MM-DD
    time_window: tuple[str, str]
    days: int
    budget: int
    moods: list[str]
    free_text: str

    # 대화
    messages: list

    # 검색 결과
    rag_docs: list
    web_docs: list

    # 코스
    candidates: list[Place]
    verified: list[Place]
    route: list[Leg]

    # 부가 정보
    sun_times: dict
    weather: dict

    # 출력
    final_answer: str
    pending_edit: Optional[EditRequest]
    retry_count: int
