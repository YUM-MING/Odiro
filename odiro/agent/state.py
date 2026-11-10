"""LangGraph 상태 정의. PLAN.md 5-3 참고.

노드 사이를 오가는 값은 전부 JSON 으로 직렬화 가능한 dict/list 로 둔다 (SSE·캐시·디버깅이 쉬워서).
Place/Leg Pydantic 모델은 타입 참고용 + 테스트용이며, API 응답 스키마는 odiro.api.schemas 가 따로 정의한다.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

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
    # 입력 (CourseRequest.model_dump())
    request: dict[str, Any]

    # parse_intent
    center: dict[str, Any] | None  # {lat, lng, label, name}
    region_filter: dict[str, str]  # rag_search.resolve_region 결과
    conditions: str  # 프롬프트용 조건 요약
    per_day: int

    # retrieve
    rag_docs: list[dict[str, Any]]
    web_docs: list[dict[str, Any]]
    poi_docs: list[dict[str, Any]]  # 중심 주변 실존 식당·카페 (카카오)
    weather: dict[str, Any]
    sun_times: dict[str, str]

    # draft / verify
    title: str
    candidates: list[dict[str, Any]]
    verified: list[dict[str, Any]]
    rejected: list[str]
    retry_count: int

    # route / enrich
    places: list[dict[str, Any]]
    legs: list[dict[str, Any]]

    # 수정 플라이휠
    instruction: str
    target_index: int | None
    edit_note: str
    full_redraft: bool

    # 출력
    final_answer: str
    warnings: list[str]
    trace: list[dict[str, Any]]
