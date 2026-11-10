"""API 요청/응답 스키마 (프론트와의 계약). 사람이 읽는 설명은 docs/API_SCHEMA.md.

에이전트 내부 모델(odiro.agent.state 의 Place/Leg)과 분리해, 프론트에 노출되는 필드만 여기 둔다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["outing", "trip"]
Transport = Literal["walk", "car"]
LegTransport = Literal["walk", "transit", "car"]

MOODS: tuple[str, ...] = (
    "감성/조용한",
    "힙한/트렌디",
    "뷰맛집/일몰",
    "레트로",
    "자연/산책",
    "실내(비오는날)",
    "액티비티",
    "사진맛집",
    "웨이팅적은",
    "아이동반",
    "반려동물",
)


class CourseRequest(BaseModel):
    mode: Mode = "outing"  # outing: 나들이(1일) / trip: 여행(n일)
    transport: Transport = "walk"  # walk: 뚜벅이(도보+대중교통) / car: 자차
    region: str = Field(..., min_length=1, description="지역명 자유 입력. 예) 성수동, 서울 성동구, 가평, 인천 송도")
    date: str = Field(..., description="출발일 YYYY-MM-DD")
    start_time: str = "11:00"  # HH:MM
    end_time: str = "20:00"
    days: int = Field(1, ge=1, le=3)  # trip 모드에서만 2 이상
    budget: int = Field(100_000, ge=0, description="1인 예산(원)")
    moods: list[str] = Field(default_factory=list, description="MOODS 중 다중 선택")
    free_text: str = Field("", max_length=300, description="자유 조건. 예) 비건 메뉴 꼭 포함")
    party: str = Field("", description="동행. 예) 연인, 가족(아이 2), 친구")


class PlaceOut(BaseModel):
    order: int  # 하루 안에서 방문 순서 (1부터)
    day: int = 1
    name: str
    category: str = ""  # 식당 / 카페 / 관광지 / 놀거리 / 숙소 ...
    lat: float
    lng: float
    address: str = ""
    kakao_place_id: str = ""
    place_url: str = ""  # 카카오맵 상세 링크
    phone: str = ""
    reason: str = ""  # 추천 이유 (LLM)
    tags: list[str] = Field(default_factory=list)
    review_summary: str = ""  # 조건 관점 한 줄 요약 (summarize_reviews)
    arrive: str = ""  # HH:MM 도착 예정
    stay_min: int = 60
    image: str = ""
    verified: bool = True  # 지도 API 로 실존 확인됨 (false 인 장소는 절대 지도에 올리지 않음)
    source: str = ""  # rag / web / llm


class LegOut(BaseModel):
    from_idx: int  # places 배열 인덱스
    to_idx: int
    transport: LegTransport
    duration_min: int
    distance_m: int
    polyline: list[list[float]] = Field(default_factory=list)  # [[lat, lng], ...]
    estimated: bool = False  # 길찾기 API 실패 → 직선거리 추정


class WeatherOut(BaseModel):
    available: bool = False
    summary: str = ""  # 맑음 / 비 ...
    temp_c: float | None = None
    pop: float | None = None  # 강수확률 0~1
    rain: bool = False  # 실내 전환 권고 기준
    note: str = ""  # "예보 범위(5일) 밖" 등


class SunOut(BaseModel):
    sunrise: str = ""  # HH:MM
    sunset: str = ""


class TraceStep(BaseModel):
    node: str
    status: Literal["start", "done", "skip", "error"]
    ms: int = 0
    detail: str = ""


class CourseMeta(BaseModel):
    sun: SunOut = Field(default_factory=SunOut)
    weather: WeatherOut = Field(default_factory=WeatherOut)
    rag_docs: int = 0
    web_docs: int = 0
    warnings: list[str] = Field(default_factory=list)
    trace: list[TraceStep] = Field(default_factory=list)
    cached: bool = False
    elapsed_ms: int = 0


class CourseResponse(BaseModel):
    course_id: str
    request: CourseRequest
    title: str = ""  # 코스 제목 (LLM)
    places: list[PlaceOut]
    legs: list[LegOut]
    answer_md: str  # 채팅창에 보여줄 스토리텔링 (markdown)
    meta: CourseMeta = Field(default_factory=CourseMeta)


class EditRequest(BaseModel):
    course: CourseResponse
    instruction: str = Field(..., min_length=1, description="예) 두 번째 장소를 실내로 바꿔줘")
    target_order: int | None = None  # 빠른 수정 버튼이 지정. 없으면 LLM 이 instruction 에서 추론
    target_day: int = 1


class JobStarted(BaseModel):
    job_id: str
    stream_url: str


# SSE 이벤트 (GET /api/course/stream/{job_id})
#   event: progress  data: TraceStep
#   event: result    data: CourseResponse
#   event: error     data: {"message": str}
