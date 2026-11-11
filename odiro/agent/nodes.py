"""LangGraph 노드 구현.

parse_intent → retrieve(RAG ∥ 웹 ∥ 날씨 ∥ 일출) → draft_course → verify_places(예비 후보로 채우고 부족하면 LLM 1회 보충)
    → optimize_route → enrich → compose_answer
modify(수정 요청) → verify_places → optimize_route → enrich → compose_answer

상태(state)는 dict 로 다룬다 (odiro.agent.state.CourseState 키). 각 노드는 바뀐 키만 돌려준다.
모든 외부 호출은 Tool 쪽에서 타임아웃·캐시·폴백을 책임지고, 노드는 '실패해도 다음 단계가 돌아가게' 만 신경 쓴다.
"""

from __future__ import annotations

import itertools
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from odiro.agent.llm import chat
from odiro.api.schemas import MOODS
from odiro.tools import get_route, get_sun_times, get_weather, search_place, summarize_reviews
from odiro.tools import rag_search as rag
from odiro.tools._util import haversine_m

log = logging.getLogger("odiro.agent")

MAX_VERIFY_ROUNDS = 1  # 예비 후보(spares)로 먼저 채우고, 그래도 비면 LLM 보충 1회
MAX_PLACES_PER_DAY = 6
MAX_PLACES_PER_DAY_TRIP = 5
MIN_PLACES_PER_DAY = 3
SPARES_PER_DAY = 3
VERIFY_RADIUS = {"walk": 2500, "car": 30000}
# 카카오 카테고리 대분류 중 코스 장소가 될 수 없는 것 (이름이 완전히 같으면 예외)
NON_VENUE_TOP_CATEGORIES = {"부동산", "의료,건강", "금융,보험", "행정,사회기관", "교육,학문", "서비스,산업", "가정,생활", "교통,수송"}
WALK_OUTLIER_M = 1100  # 뚜벅이: 그날 동선의 한가운데 장소에서 직선으로 이보다 멀면(도보 약 20분+) 동선에서 뺀다
# RAG 장소 문서를 중심에서 이 거리 안쪽만 쓴다. "인천 송도" 처럼 동 단위 요청은 시도 전체가 검색돼 코스가 퍼지기 때문.
RAG_RADIUS_M = {"walk": 3000, "car_local": 8000, "car_wide": 30000}
PLAY_CATEGORIES = {"관광지", "놀거리", "산책", "쇼핑", "기타"}  # 비 예보 때 실내 여부를 따지는 역할 (식당·카페·숙소는 실내로 본다)


# ---------- LLM 출력 스키마 ----------


class DraftPlace(BaseModel):
    name: str = Field(description="실제 존재하는 구체적 상호/장소명. 체인점이면 지점명까지. 예) '어니언 성수', '서울숲'")
    category: Literal["식당", "카페", "관광지", "놀거리", "산책", "쇼핑", "숙소", "기타"]
    reason: str = Field(description="이 조건에 왜 맞는지 1문장 (근거 문서가 있으면 그 내용으로)")
    stay_min: int = Field(60, ge=20, le=180)
    indoor: bool = Field(True, description="실내에서 머무는 곳이면 true (전시·박물관·식당·카페·쇼핑몰·실내 체험). 공원·수목원·호수·섬·산책로·전망대·야외 거리는 false")
    tags: list[str] = Field(default_factory=list, description=f"해당하는 분위기 태그. 가능한 값: {', '.join(MOODS)}")
    source: Literal["rag", "web", "llm"] = Field("llm", description="근거 출처: 제공된 큐레이션 문서=rag, 웹검색=web, 일반지식=llm")


class DraftDay(BaseModel):
    day: int = 1
    places: list[DraftPlace] = Field(description="방문 순서대로, 요구된 개수만큼")
    spares: list[DraftPlace] = Field(default_factory=list, description="지도 확인에 실패할 때 대신 쓸 예비 후보 2~3개 (역할 다양하게)")


class CourseDraft(BaseModel):
    title: str = Field(description="코스 제목 (15자 이내, 감성적으로)")
    days: list[DraftDay]


class Replacement(BaseModel):
    slot: int = Field(description="교체할 후보의 인덱스 (입력에서 준 번호)")
    place: DraftPlace


class Replacements(BaseModel):
    items: list[Replacement]


class EditPlan(BaseModel):
    target_number: int = Field(description="바꿀 장소의 번호 (현재 코스 목록의 '번호', 1부터). 전체 재구성 요청이면 0")
    place: DraftPlace | None = Field(None, description="그 자리에 넣을 새 장소. 전체 재구성이면 null")
    alternates: list[DraftPlace] = Field(default_factory=list, description="place 가 지도에서 확인되지 않을 때 대신 쓸, 같은 요청을 만족하는 다른 실존 장소 2~3개")
    keywords: list[str] = Field(default_factory=list, description="새 장소를 지도 앱에서 찾을 때 쓸 업종 검색어 2~3개 (지도에 실제로 쓰이는 짧은 업종명). 예) ['키즈카페', '실내놀이터'], ['미술관', '전시'], ['브런치']. 지역명·수식어는 넣지 않는다")
    note: str = Field("", description="사용자에게 한 줄로 전할 변경 요약")


# ---------- 공통 ----------


def _now_ms() -> int:
    return int(time.time() * 1000)


def _conditions_text(req: dict[str, Any]) -> str:
    mode = "나들이(1일 데이트/나들이)" if req.get("mode") == "outing" else f"여행 {req.get('days', 1)}일"
    transport = "뚜벅이(도보+대중교통, 장소 간 짧게)" if req.get("transport") == "walk" else "자차(주차 편한 곳, 반경 넓게 OK)"
    parts = [
        f"지역: {req.get('region')}",
        f"모드: {mode}",
        f"이동: {transport}",
        f"날짜: {req.get('date')} {req.get('start_time')}~{req.get('end_time')}",
        f"1인 예산: {int(req.get('budget', 0)):,}원",
    ]
    if req.get("moods"):
        parts.append("분위기: " + ", ".join(req["moods"]))
    if req.get("party"):
        parts.append(f"동행: {req['party']}")
    if req.get("free_text"):
        parts.append(f"추가 조건: {req['free_text']}")
    return "\n".join(parts)


def _places_per_day(req: dict[str, Any]) -> int:
    try:
        sh, sm = map(int, req.get("start_time", "11:00").split(":"))
        eh, em = map(int, req.get("end_time", "20:00").split(":"))
        hours = max(2.0, (eh * 60 + em - sh * 60 - sm) / 60)
    except ValueError:
        hours = 8.0
    n = round(hours / 1.8)
    cap = MAX_PLACES_PER_DAY_TRIP if req.get("mode") == "trip" else MAX_PLACES_PER_DAY
    return max(MIN_PLACES_PER_DAY, min(cap, n))


def _fmt_rag_docs(docs: list[dict[str, Any]], limit: int = 20) -> str:
    lines = []
    for d in docs[:limit]:
        if d.get("doc_type") == "place":
            lines.append(f"- [장소 ✔지도확인] {d.get('title')} ({d.get('content_type', '')}, {d.get('addr', '')}) — {d.get('one_line') or ''} {d.get('tags') or ''}")
        else:
            lines.append(f"- [블로그] {d.get('title')} — {d.get('one_line') or d.get('snippet', '')[:120]} {d.get('tags') or ''}")
    return "\n".join(lines) or "- (없음)"


def _fmt_pois(pois: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {p['name']} ({p.get('category_full', '').split(' > ')[-1] or p.get('category')}, {p.get('address', '')})" for p in pois
    ) or "- (없음)"


def _trip_days(req: dict[str, Any]) -> int:
    return int(req.get("days", 1)) if req.get("mode") == "trip" else 1


def _max_outdoor(req: dict[str, Any]) -> int:
    """비 예보일 때 Day 당 허용하는 야외 장소 수. 자연/산책을 고른 사용자는 하나 더."""
    return 2 if "자연/산책" in (req.get("moods") or []) else 1


def _is_outdoor(p: dict[str, Any]) -> bool:
    return p.get("category") in PLAY_CATEGORIES and not p.get("indoor", True)


def _enforce_rain(cands: list[dict[str, Any]], spares: list[dict[str, Any]], max_outdoor: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """비 예보: Day 마다 야외 장소가 max_outdoor 를 넘으면 뒤쪽부터 같은 날의 실내 예비 후보로 바꾼다.

    반환: (cands, 남은 spares, 바꾸지 못하고 남은 초과 야외 장소 수)
    """
    cands, spares = list(cands), list(spares)
    leftover = 0
    for day in sorted({c["day"] for c in cands}):
        outdoor = [i for i, c in enumerate(cands) if c["day"] == day and _is_outdoor(c)]
        for i in reversed(outdoor[max_outdoor:]):
            pick = next((s for s in spares if s["day"] == day and s.get("category") in PLAY_CATEGORIES and s.get("indoor", True)), None)
            if pick is None:
                leftover += 1
                continue
            spares.remove(pick)
            cands[i] = {**pick, "order": cands[i]["order"], "day": day}
    return cands, spares, leftover


_ORDINALS = {"첫": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "네": 4, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8}
_ORDINAL_RE = re.compile(r"(\d+|첫|두|둘|세|셋|네|넷|다섯|여섯|일곱|여덟)\s*번\s*째")
_DAY_RE = re.compile(r"(?:day|데이)\s*(\d)|(\d)\s*일\s*차|(첫|둘|셋)\s*째?\s*날", re.IGNORECASE)


def _parse_target(instruction: str, places: list[dict[str, Any]]) -> int | None:
    """'3번째를 실내로', '마지막 장소를 …', '2일차 첫 번째' 처럼 순서로 가리킨 수정 대상을 places 인덱스로 바꾼다.

    LLM 에게 맡기면 0/1 기준이 섞여 한 칸씩 밀리는 일이 있어, 순서 표현이 정확히 하나일 때는 여기서 확정한다. 모르면 None.
    """
    if not places:
        return None
    day = None
    m = _DAY_RE.search(instruction)
    if m:
        day = int(m.group(1) or m.group(2) or 0) or _ORDINALS.get(m.group(3) or "")
    pool = [i for i, p in enumerate(places) if day is None or p.get("day", 1) == day]
    if not pool:
        return None
    ords = _ORDINAL_RE.findall(instruction)
    has_last = "마지막" in instruction or "맨 끝" in instruction
    if len(ords) + int(has_last) != 1:
        return None
    if has_last:
        return pool[-1]
    n = int(ords[0]) if ords[0].isdigit() else _ORDINALS[ords[0]]
    return pool[n - 1] if 1 <= n <= len(pool) else None


def _radius_key(req: dict[str, Any]) -> str:
    """뚜벅이 / 자차(동 단위 요청: 시군구까지 해석되지 않음) / 자차(시군구 단위 요청)."""
    if req.get("transport", "walk") == "walk":
        return "walk"
    return "car_wide" if "sigungu_code" in rag.resolve_region(req.get("region")) else "car_local"


def _near_center(docs: list[dict[str, Any]], center: dict[str, Any], radius_m: int) -> list[dict[str, Any]]:
    """좌표가 있는 장소 문서 중 중심에서 radius_m 보다 먼 것을 뺀다 (좌표 없는 블로그 문서는 그대로)."""
    return [
        d for d in docs
        if not (d.get("lat") and d.get("lng")) or haversine_m(center["lat"], center["lng"], float(d["lat"]), float(d["lng"])) <= radius_m
    ]


def _find_stays(req: dict[str, Any], center: dict[str, Any] | None) -> list[dict[str, Any]]:
    """중심 주변의 실존 숙소 (카카오 카테고리 AD5)."""
    if not center:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for q in ("숙소", "펜션", "호텔"):
            for h in search_place.search(f"{req['region']} {q}", center["lat"], center["lng"], 20000, size=15):
                if h.get("category_group") == "AD5" and h.get("kakao_place_id") not in seen:
                    seen.add(h.get("kakao_place_id"))
                    out.append(h)
    except Exception as e:  # noqa: BLE001
        log.warning("숙소 검색 실패: %s", e)
    return out[:12]


def _fmt_web_docs(docs: list[dict[str, Any]], limit: int = 5) -> str:
    return "\n".join(f"- {d.get('title')}: {d.get('content', '')[:160]}" for d in docs[:limit]) or "- (없음)"


# ---------- 노드 ----------


def parse_intent(state: dict[str, Any]) -> dict[str, Any]:
    req = state["request"]
    t0 = _now_ms()
    center = None
    try:
        center = search_place.geocode_region(req["region"])
    except Exception as e:  # noqa: BLE001
        log.warning("geocode 실패: %s", e)
    region_filter = rag.resolve_region(req["region"])
    warnings = list(state.get("warnings", []))
    if not center:
        warnings.append(f"'{req['region']}' 위치를 찾지 못해 지역 중심 없이 진행합니다")
    detail = f"{req['region']} → {center['label'] if center else '?'}"
    return {
        "center": center,
        "region_filter": region_filter,
        "conditions": _conditions_text(req),
        "per_day": _places_per_day(req),
        "warnings": warnings,
        "trace": state.get("trace", []) + [{"node": "parse_intent", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def retrieve(state: dict[str, Any]) -> dict[str, Any]:
    req, center = state["request"], state.get("center")
    t0 = _now_ms()
    moods = req.get("moods") or []
    base_q = f"{req['region']} {' '.join(moods)} {req.get('free_text', '')} {'데이트' if req.get('mode') == 'outing' else '여행'} 코스".strip()

    def do_rag() -> list[dict[str, Any]]:
        try:
            places = rag.search(base_q, moods=moods, region=req["region"], k=8, doc_type="place")
            # 식당·카페 후보가 빠지지 않도록 따로 뽑는다 (TourAPI 장소 문서는 관광지 비중이 커서)
            eats = rag.search(f"{req['region']} 맛집 식당 {' '.join(moods)}", moods=None, region=req["region"], k=5, doc_type="blog")
            cafes = rag.search(f"{req['region']} 카페 {' '.join(moods)}", moods=None, region=req["region"], k=4, doc_type="blog")
            blogs = rag.search(base_q, moods=moods, region=req["region"], k=6, doc_type="blog")
            seen: set[str] = set()
            out: list[dict[str, Any]] = []
            for d in places + eats + cafes + blogs:
                if d["doc_id"] not in seen:
                    seen.add(d["doc_id"])
                    out.append(d)
            return out
        except Exception as e:  # noqa: BLE001
            log.warning("rag 실패: %s", e)
            return []

    def do_web() -> list[dict[str, Any]]:
        q1 = f"{req['region']} {'데이트' if req.get('mode') == 'outing' else '여행'} 코스 추천 {' '.join(moods)}".strip()
        q2 = f"{req['region']} 팝업 전시 축제 이번주"
        return summarize_reviews.web_search(q1, 4) + summarize_reviews.web_search(q2, 3, days=14)

    def do_weather() -> dict[str, Any]:
        if not center:
            return {"available": False, "rain": False, "note": "위치 없음"}
        sh = int(req.get("start_time", "11:00").split(":")[0])
        eh = int(req.get("end_time", "20:00").split(":")[0])
        return get_weather.weather(center["lat"], center["lng"], req["date"], sh, max(eh, sh + 1))

    def do_sun() -> dict[str, str]:
        lat, lng = (center["lat"], center["lng"]) if center else (37.5665, 126.9780)
        return get_sun_times.sun_times(lat, lng, req["date"])

    def do_pois() -> list[dict[str, Any]]:
        """중심 주변의 실존 식당·카페 (카카오). LLM 이 지어내지 않고 여기서 고르게 한다."""
        if not center:
            return []
        radius = 1500 if req.get("transport") == "walk" else 8000
        out: list[dict[str, Any]] = []
        try:
            # 분위기 단어를 섞으면 카카오 검색이 비어 버리므로 업종 키워드만 쓴다. 분위기 판단은 LLM 이 RAG 문서로 한다.
            for q, group in (("맛집", "FD6"), ("카페", "CE7")):
                hits = search_place.search(f"{req['region']} {q}", center["lat"], center["lng"], radius, size=15)
                picked = [h for h in hits if h.get("category_group", group) == group]
                out += picked[:8]
        except Exception as e:  # noqa: BLE001
            log.warning("poi 검색 실패: %s", e)
        return out

    def do_stays() -> list[dict[str, Any]]:
        return _find_stays(req, center) if _trip_days(req) > 1 else []

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_rag, f_web, f_wx, f_sun, f_poi, f_stay = (
            ex.submit(do_rag), ex.submit(do_web), ex.submit(do_weather), ex.submit(do_sun), ex.submit(do_pois), ex.submit(do_stays)
        )
        rag_docs, web_docs, weather, sun, pois, stays = (
            f_rag.result(), f_web.result(), f_wx.result(), f_sun.result(), f_poi.result(), f_stay.result()
        )

    warnings = list(state.get("warnings", []))
    if weather.get("rain"):
        warnings.append(f"비 예보(강수확률 {int((weather.get('pop') or 0) * 100)}%) → 실내 위주로 구성했어요")
        # 분위기 태그가 야외 쪽(자연/산책 등)이면 실내 후보가 거의 안 잡히므로 실내 문서를 따로 더 뽑는다
        try:
            seen = {d["doc_id"] for d in rag_docs}
            q = f"{req['region']} 실내 비오는날 전시 박물관 체험"
            indoor = rag.search(q, moods=["실내(비오는날)"], region=req["region"], k=6, doc_type="place") + rag.search(
                q, moods=["실내(비오는날)"], region=req["region"], k=4, doc_type="blog"
            )
            rag_docs = [d for d in indoor if d["doc_id"] not in seen] + rag_docs
        except Exception as e:  # noqa: BLE001
            log.warning("실내 rag 실패: %s", e)
    if center:
        rag_docs = _near_center(rag_docs, center, RAG_RADIUS_M[_radius_key(req)])
    detail = f"RAG {len(rag_docs)}건 / 웹 {len(web_docs)}건 / 주변 식당·카페 {len(pois)}곳 / 날씨 {weather.get('summary') or weather.get('note', '-')}"
    if stays:
        detail += f" / 숙소 {len(stays)}곳"
    return {
        "rag_docs": rag_docs,
        "web_docs": web_docs,
        "poi_docs": pois,
        "stay_docs": stays,
        "weather": weather,
        "sun_times": sun,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "retrieve", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


DRAFT_SYSTEM = """당신은 Odiro, 국내 여행·데이트 코스 플래너입니다. 사용자 조건에 맞는 코스를 JSON 으로 설계합니다.

원칙
1. **실제로 존재하는 구체적인 장소명만** 씁니다. 모호한 표현("성수동 감성 카페")이나 지어낸 상호는 금지. 확신이 없으면 유명한 곳을 고릅니다.
   장소명은 지도 앱에 등록된 공식 명칭으로 (예: "가평레일파크", "쁘띠프랑스", "어니언 성수").
2. **[장소 ✔지도확인]** 문서와 **"주변 실존 식당·카페"** 목록은 실존이 확인된 장소입니다. 식당·카페는 가능한 한 이 목록에서 고르고(조건에 맞는 것으로),
   source="rag" 로 표기합니다. 블로그 글에 나온 상호를 쓰면 source="rag", 웹검색은 "web", 일반 지식은 "llm".
3. **Day 마다 반드시 식당 1곳 이상 + 카페 1곳 이상** 을 넣고 나머지를 관광지·놀거리·산책으로 채웁니다 (나들이 뼈대 "밥 1 + 카페 1 + 놀거리 1 + α").
   식사 시간대(11:30~13:30, 17:30~19:30)에 식당이 오도록 순서를 잡습니다. category 는 실제 업종대로 (카페거리·상업시설은 '놀거리', 복합문화공간은 '관광지').
   여행 모드는 Day 별로, 마지막 Day 를 제외하고 숙소를 마지막에 둡니다.
4. 뚜벅이는 장소 간 도보 15분 안쪽(약 1km)으로 촘촘하게, 자차는 반경을 넓혀도 됩니다.
5. 비 예보면 실내(전시·대형 카페·박물관·쇼핑) 위주로, 일몰 태그가 있으면 일몰 시각 즈음 뷰 좋은 곳을 배치합니다.
6. 예산을 넘기지 않게 (1인 식사 1.5~3만, 카페 1만, 입장료 0~2만 기준). 체류 시간은 식당 60~90, 카페 60, 관광지 60~120 분.
7. 같은 장소를 두 번 넣지 않고, 요청된 개수만큼 정확히 채웁니다. Day 마다 예비 후보(spares) 2~3개를 따로 둡니다."""


def _draft_prompt(state: dict[str, Any], exclude: list[str] | None = None) -> str:
    req = state["request"]
    days = req.get("days", 1) if req.get("mode") == "trip" else 1
    per_day = state.get("per_day", 4)
    wx = state.get("weather") or {}
    wx_line = (
        f"{wx.get('summary')} {wx.get('temp_c')}°C 강수확률 {int((wx.get('pop') or 0) * 100)}%" + (" ⚠ 비" if wx.get("rain") else "")
        if wx.get("available")
        else f"(예보 없음: {wx.get('note', '')})"
    )
    sun = state.get("sun_times") or {}
    center = state.get("center") or {}
    anchor = center.get("label") or req["region"]
    radius_rule = (
        f"모든 장소는 '{anchor}' 중심 반경 1.5km 안 (도보 이동, 장소 간 15분 이내)"
        if req.get("transport") == "walk"
        else f"장소는 '{anchor}' 기준 차로 30~40분 안, 주차 가능한 곳 위주"
    )
    lines = [
        f"## 사용자 조건\n{state['conditions']}\n{radius_rule}",
        f"## 날씨 / 일출·일몰\n{wx_line} / 일출 {sun.get('sunrise', '?')} 일몰 {sun.get('sunset', '?')}",
        f"## 큐레이션 문서 (RAG)\n{_fmt_rag_docs(state.get('rag_docs', []))}",
        f"## 주변 실존 식당·카페 (카카오 지도, ✔지도확인)\n{_fmt_pois(state.get('poi_docs', []))}",
        f"## 웹 검색\n{_fmt_web_docs(state.get('web_docs', []))}",
        f"## 요구 구조\nDay 수: {days}, Day 당 장소 {per_day}개 (정확히) + 예비 {SPARES_PER_DAY}개. 방문 순서대로.",
    ]
    if wx.get("rain"):
        lines.append(
            f"## ⚠ 비 예보 규칙 (반드시 지킬 것)\nDay 마다 야외 장소(indoor=false: 공원·수목원·호수·섬·산책로·전망대·야외 거리)는 최대 {_max_outdoor(req)}곳. "
            "나머지 관광지·놀거리와 예비 후보(spares)는 전부 실내(indoor=true: 전시·박물관·미술관·실내 체험·쇼핑몰·대형 카페)로 고릅니다."
        )
    if days > 1:
        lines.append(
            f"## 숙소 규칙 (반드시 지킬 것)\nDay 1~{days - 1} 의 **마지막 장소는 category='숙소'** 로, 아래 실존 숙소 목록에서 고릅니다 (Day 당 장소 수에 포함). "
            f"Day {days} 에는 숙소를 넣지 않습니다.\n{_fmt_pois(state.get('stay_docs', []))}"
        )
    if exclude:
        lines.append("## 제외 (이미 쓰였거나 존재 확인 실패)\n" + ", ".join(exclude))
    return "\n\n".join(lines)


def draft_course(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    try:
        draft: CourseDraft = chat(0.4).with_structured_output(CourseDraft).invoke(
            [("system", DRAFT_SYSTEM), ("human", _draft_prompt(state, exclude=state.get("rejected") or None))]
        )
    except Exception as e:  # noqa: BLE001
        log.error("draft 실패: %s", e)
        return {
            "candidates": [],
            "spares": [],
            "title": f"{state['request']['region']} 코스",
            "trace": state["trace"] + [{"node": "draft_course", "status": "error", "ms": _now_ms() - t0, "detail": str(e)[:80]}],
        }
    cap = MAX_PLACES_PER_DAY_TRIP if state["request"].get("mode") == "trip" else MAX_PLACES_PER_DAY
    cands: list[dict[str, Any]] = []
    spares: list[dict[str, Any]] = []
    days = _trip_days(state["request"])
    for d in draft.days:
        # 숙소는 마지막 날(나들이는 당일)에는 넣지 않는다
        kept = [p for p in d.places[:cap] if not (p.category == "숙소" and d.day >= days)]
        extra_spares = [p for p in d.spares if p.category != "숙소"]
        while len(kept) < len(d.places[:cap]) and extra_spares:  # 뺀 숙소 자리는 예비 후보로 채워 장소 수를 유지
            kept.append(extra_spares.pop(0))
        promoted = {p.name for p in kept}
        for i, p in enumerate(kept, 1):
            cands.append({**p.model_dump(), "day": d.day, "order": i, "verified": False})
        for p in [p for p in d.spares if p.name not in promoted][:SPARES_PER_DAY + 1]:
            spares.append({**p.model_dump(), "day": d.day, "order": 0, "verified": False})
    detail = f"{len(cands)}곳 초안 + 예비 {len(spares)} ({sum(1 for c in cands if c['source'] == 'rag')} RAG 근거)"
    out: dict[str, Any] = {}
    if (state.get("weather") or {}).get("rain"):
        before = sum(1 for c in cands if _is_outdoor(c))
        cands, spares, leftover = _enforce_rain(cands, spares, _max_outdoor(state["request"]))
        swapped = before - sum(1 for c in cands if _is_outdoor(c))
        if swapped:
            detail += f", 비 예보로 야외 {swapped}곳 → 실내"
        if leftover:
            out["warnings"] = list(state.get("warnings", [])) + [f"실내 대안을 찾지 못해 야외 장소가 {leftover}곳 더 들어갔어요. 우산을 챙기세요"]
    return {
        **out,
        "candidates": cands,
        "spares": spares,
        "title": draft.title,
        "trace": state["trace"] + [{"node": "draft_course", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _verify_one(c: dict[str, Any], center: dict[str, Any] | None, radius: int, hint: str) -> dict[str, Any]:
    if c.get("verified") and c.get("lat") and c.get("lng"):
        return c  # 수정 흐름에서 이미 검증된 장소
    hit = None
    names = [c["name"]]
    tokens = c["name"].split()
    if len(tokens) >= 3:  # '성수동 애견동반카페 따우전드 성수' → '따우전드 성수' 처럼 수식어를 떼고 한 번 더
        names.append(" ".join(tokens[-2:]))
    try:
        for nm in names:
            if center:
                hit = search_place.verify(nm, center["lat"], center["lng"], radius, hint)
            else:
                res = search_place.search(f"{hint} {nm}", size=3)
                hit = res[0] if res else None
            if hit:
                break
    except Exception as e:  # noqa: BLE001
        log.warning("verify 오류 %s: %s", c["name"], e)
    if not hit:
        return {**c, "verified": False}
    cat = c.get("category") or ""
    group = hit.get("category_group", "")
    # 코스에 올릴 수 없는 업종 (주거·의료·행정 등). 카카오 카테고리 대분류로 거른다.
    top = (hit.get("category_full") or "").split(" > ")[0]
    if top in NON_VENUE_TOP_CATEGORIES and search_place._norm_name(c["name"]) != search_place._norm_name(hit["name"]):
        return {**c, "verified": False}
    # 역할 불일치 방지: '청평호(관광지)' 가 '청평호반닭갈비(식당)' 로 매칭되는 류. 이름이 완전히 같을 때만 예외.
    exact = search_place._norm_name(c["name"]) == search_place._norm_name(hit["name"])
    if not exact:
        if cat in ("관광지", "산책", "놀거리", "쇼핑") and group in ("FD6", "CE7", "AD5"):
            return {**c, "verified": False}
        if cat == "식당" and group in ("AT4", "CT1", "AD5"):
            return {**c, "verified": False}
        if cat == "숙소" and group and group != "AD5":
            return {**c, "verified": False}
    if cat in ("기타", "") and hit.get("category"):
        cat = hit["category"]
    return {
        **c,
        "verified": True,
        "name": hit["name"],
        "category": cat,
        "lat": hit["lat"],
        "lng": hit["lng"],
        "address": hit.get("address", ""),
        "kakao_place_id": hit.get("kakao_place_id", ""),
        "place_url": hit.get("place_url", ""),
        "phone": hit.get("phone", ""),
        "kakao_category": hit.get("category_full", ""),
    }


def _same_role(a: str, b: str) -> bool:
    food = {"식당"}
    cafe = {"카페"}
    play = {"관광지", "놀거리", "산책", "쇼핑", "기타"}
    for group in (food, cafe, play, {"숙소"}):
        if a in group and b in group:
            return True
    return a == b


def verify_places(state: dict[str, Any]) -> dict[str, Any]:
    """카카오 지도에 없는 장소는 버리고, 빈 자리는 예비 후보 → (부족하면) LLM 보충 1회로 채운다."""
    t0 = _now_ms()
    req, center = state["request"], state.get("center")
    radius = VERIFY_RADIUS.get(req.get("transport", "walk"), 5000)
    if _radius_key(req) == "car_local":  # "인천 송도" 같은 동 단위 요청은 자차여도 그 동네 안에서
        radius = RAG_RADIUS_M["car_local"]
    hint = req["region"]
    cands = list(state.get("candidates", []))
    spares = list(state.get("spares", []))
    rejected: list[str] = list(state.get("rejected", []))

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda c: _verify_one(c, center, radius, hint), cands + spares))
    cands, spares = results[: len(cands)], results[len(cands) :]
    used_ids = {c.get("kakao_place_id") for c in cands if c["verified"]}
    spare_pool = [s for s in spares if s["verified"] and s.get("kakao_place_id") not in used_ids]
    spares_used = 0

    slot = state.get("edit_slot") if not state.get("full_redraft") else None  # 수정 흐름: 바꾸는 자리 하나
    walk = req.get("transport", "walk") == "walk"
    # 수정 흐름에서는 사용자가 이미 본 나머지 장소를 건드리지 않는다 → 거리 검사는 바꾸는 자리만
    checkable = {slot["index"]} if slot else set(range(len(cands)))

    def nearest_m(i: int, p: dict[str, Any]) -> float | None:
        """같은 날 다른 확인된 장소들의 한가운데 장소(medoid: 나머지와의 거리 합이 가장 작은 곳)까지의 직선거리.

        가장 가까운 이웃이 아니라 medoid 로 재야, 두 무리로 갈라진 코스(무리 사이 도보 25분)도 걸러진다.
        """
        others = [c for j, c in enumerate(cands) if j != i and c["verified"] and c["day"] == p["day"]]
        if len(others) < 2:
            return None
        hub = min(others, key=lambda a: sum(haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) for b in others))
        return haversine_m(p["lat"], p["lng"], hub["lat"], hub["lng"])

    def drop_walk_outliers() -> None:
        """뚜벅이: 동선 중심에서 멀리 떨어진 장소(도보 20분+)는 미확인 처리해 예비 후보·LLM 보충으로 다시 채우게 한다."""
        if not walk:
            return
        while True:
            far = [(d, i) for i in checkable if cands[i]["verified"] and (d := nearest_m(i, cands[i])) is not None and d > WALK_OUTLIER_M]
            if not far:
                return
            _, i = max(far)
            rejected.append(cands[i]["name"])
            cands[i] = {**cands[i], "verified": False, "too_far": True, "too_far_orig": dict(cands[i])}

    def drop_duplicates() -> None:
        """같은 장소가 두 번 들어가면(이름만 다르게 적힌 경우 포함) 뒤쪽을 미확인 처리해 다시 채우게 한다."""
        key = lambda c: c.get("kakao_place_id") or c["name"]
        if slot:  # 수정 흐름: 새로 넣는 자리만 검사 (나머지는 건드리지 않는다)
            i = slot["index"]
            if cands[i]["verified"] and any(j != i and c["verified"] and key(c) == key(cands[i]) for j, c in enumerate(cands)):
                rejected.append(cands[i]["name"])
                cands[i] = {**cands[i], "verified": False}
            return
        seen_ids: set[str] = set()
        for i, c in enumerate(cands):
            if not c["verified"]:
                continue
            if key(c) in seen_ids:
                rejected.append(c["name"])
                cands[i] = {**c, "verified": False}
            seen_ids.add(key(c))

    def fill_from_spares() -> None:
        nonlocal spares_used
        for i, c in enumerate(cands):
            if c["verified"]:
                continue
            in_use = {x.get("kakao_place_id") for x in cands if x["verified"]}
            ok = [
                s for s in spare_pool
                if s["day"] == c["day"] and s.get("kakao_place_id") not in in_use and not (walk and (d := nearest_m(i, s)) is not None and d > WALK_OUTLIER_M)
            ]
            pick = next((s for s in ok if _same_role(s["category"], c["category"])), None)
            if pick is None and not slot:  # 수정 흐름에서는 역할이 다른 장소로 대신하지 않는다 (식당 자리가 관광지로 바뀌는 일 방지)
                pick = next(iter(ok), None)
            if pick:
                spare_pool.remove(pick)
                spares_used += 1
                if c["name"] not in rejected:
                    rejected.append(c["name"])
                cands[i] = {**pick, "order": c["order"], "day": c["day"]}

    drop_duplicates()
    drop_walk_outliers()
    fill_from_spares()
    rounds = 0
    while rounds < MAX_VERIFY_ROUNDS and any(not c["verified"] for c in cands):
        missing = [i for i, c in enumerate(cands) if not c["verified"]]
        rejected += [cands[i]["name"] for i in missing]
        rounds += 1
        used = [c["name"] for c in cands if c["verified"]]
        prompt = (
            _draft_prompt(state, exclude=rejected + used)
            + "\n\n## 요청\n아래 슬롯의 장소가 지도에서 확인되지 않았습니다. 각 슬롯에 **같은 역할(카테고리)** 의, 지도 앱에 확실히 등록된 유명한 장소를 제안하세요.\n"
            + "\n".join(
                f"- 슬롯 {i}: Day {cands[i]['day']} {cands[i]['order']}번째, 역할 {cands[i]['category']}, 원래 제안 '{cands[i]['name']}'"
                + (" (다른 장소들과 너무 멀어 제외 → 도보 15분 안쪽으로)" if cands[i].get("too_far") else "")
                for i in missing
            )
            + (f"\n\n## 사용자 수정 요청 (새 장소는 이 요청을 만족해야 함)\n{state['instruction']}" if slot and state.get("instruction") else "")
        )
        try:
            reps: Replacements = chat(0.5).with_structured_output(Replacements).invoke([("system", DRAFT_SYSTEM), ("human", prompt)])
        except Exception as e:  # noqa: BLE001
            log.warning("대체 후보 요청 실패: %s", e)
            break
        by_slot = {r.slot: r.place for r in reps.items if r.slot in missing}
        todo = [i for i in missing if i in by_slot]
        for i in todo:
            cands[i] = {**cands[i], **by_slot[i].model_dump(), "verified": False}
        if not todo:
            break
        with ThreadPoolExecutor(max_workers=8) as ex:
            res = list(ex.map(lambda i: _verify_one(cands[i], center, radius, hint), todo))
        for i, r in zip(todo, res, strict=True):
            cands[i] = r
        drop_duplicates()
        drop_walk_outliers()
        fill_from_spares()

    warnings = list(state.get("warnings", []))
    extra: dict[str, Any] = {}
    for i, c in enumerate(cands):
        if not c["verified"] and c.get("too_far_orig") and not (slot and slot["index"] == i):
            cands[i] = c["too_far_orig"]  # 대신할 곳을 못 찾았으면 지우지 않고 원래 장소를 두되 알린다
            warnings.append(f"'{cands[i]['name']}' 은(는) 다른 장소들과 조금 떨어져 있어요 (도보 20분 이상)")

    # 수정 흐름: 교체 장소를 끝내 확인하지 못했거나(또는 이미 코스에 있는 곳이면) 자리를 비우지 않고 원래 장소를 유지한다.
    # 안내 문구는 처음 고른 후보가 아니라 실제로 들어간 장소 기준으로 다시 쓴다.
    if slot:
        idx, old = slot["index"], slot["old"]
        cur = cands[idx]
        dup = cur["verified"] and any(
            j != idx and c["verified"] and c.get("kakao_place_id") and c.get("kakao_place_id") == cur.get("kakao_place_id")
            for j, c in enumerate(cands)
        )
        if not cur["verified"] or dup:
            cands[idx] = {**old, "verified": True}
            extra["edit_note"] = f"요청에 맞는 장소를 지도에서 확인하지 못해 '{old['name']}' 을(를) 그대로 뒀어요"
            warnings.append(extra["edit_note"])
        else:
            note = f"{old['name']} → {cur['name']}"
            planned = slot.get("planned") or ""
            if planned and search_place.name_similarity(search_place._norm_name(planned), search_place._norm_name(cur["name"])) < search_place.MATCH_THRESHOLD:
                note += f" (처음 고른 '{planned}' 은(는) 지도에서 확인되지 않아 다른 곳으로 골랐어요)"
            extra["edit_note"] = note

    # 여행 모드: 마지막 날을 뺀 각 Day 는 숙소로 끝나야 한다. 초안에 없거나 확인에 실패했으면 주변 실존 숙소로 채운다.
    stays_added = 0
    days = _trip_days(req)
    if days > 1 and not slot:
        stays = state.get("stay_docs") or _find_stays(req, center)
        taken = {c.get("kakao_place_id") for c in cands if c["verified"]}
        for day in range(1, days):
            day_places = [c for c in cands if c["verified"] and c["day"] == day]
            if not day_places or any(c.get("category") == "숙소" for c in day_places):
                continue
            last = day_places[-1]
            pool = [s for s in stays if s.get("kakao_place_id") not in taken]
            if not pool:
                warnings.append(f"Day {day} 숙소를 찾지 못했어요. 숙소는 따로 예약해 주세요")
                continue
            s = min(pool, key=lambda h: haversine_m(last["lat"], last["lng"], h["lat"], h["lng"]))
            taken.add(s.get("kakao_place_id"))
            cands.append({
                "name": s["name"], "category": "숙소", "reason": f"Day {day} 일정을 마치고 쉬어 가는 숙소 (마지막 장소에서 가까운 곳)",
                "stay_min": 60, "indoor": True, "tags": [], "source": "rag", "day": day, "order": 99, "verified": True,
                "lat": s["lat"], "lng": s["lng"], "address": s.get("address", ""), "kakao_place_id": s.get("kakao_place_id", ""),
                "place_url": s.get("place_url", ""), "phone": s.get("phone", ""), "kakao_category": s.get("category_full", ""),
            })
            stays_added += 1

    # 미검증 제거 + 같은 장소 중복 제거
    seen: set[str] = set()
    verified: list[dict[str, Any]] = []
    for c in cands:
        if not c["verified"]:
            continue
        key = c.get("kakao_place_id") or c["name"]
        if key in seen:
            continue
        seen.add(key)
        verified.append(c)
    dropped = len(cands) - len(verified)
    if dropped:
        warnings.append(f"지도에서 확인되지 않았거나 중복된 장소 {dropped}곳을 제외했어요")
    detail = f"{len(verified)}/{len(cands)} 확인 (예비 {spares_used}개 사용, LLM 보충 {rounds}회)"
    if stays_added:
        detail += f", 숙소 {stays_added}곳 보충"
    return {
        **extra,
        "verified": verified,
        "rejected": rejected,
        "retry_count": rounds,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "verify_places", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _best_order(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 순서를 기본으로 하되, 순열 전수로 총거리가 25% 이상 줄면 그 순서를 쓴다 (n ≤ 6)."""
    # 숙소는 순서를 바꾸지 않고 항상 그날의 맨 끝에 둔다
    stays = [p for p in places if p.get("category") == "숙소"]
    if stays:
        return _best_order([p for p in places if p.get("category") != "숙소"]) + stays
    if len(places) <= 2:
        return places

    def total(order: list[dict[str, Any]]) -> int:
        return sum(haversine_m(a["lat"], a["lng"], b["lat"], b["lng"]) for a, b in itertools.pairwise(order))

    base = total(places)
    best, best_d = places, base
    if len(places) <= MAX_PLACES_PER_DAY:
        for perm in itertools.permutations(places):
            d = total(list(perm))
            if d < best_d:
                best, best_d = list(perm), d
    return best if best_d < base * 0.75 else places


def _hhmm_add(hhmm: str, minutes: int) -> str:
    t = datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


def optimize_route(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    req = state["request"]
    transport = req.get("transport", "walk")
    by_day: dict[int, list[dict[str, Any]]] = {}
    for p in state.get("verified", []):
        by_day.setdefault(p.get("day", 1), []).append(p)

    places: list[dict[str, Any]] = []
    legs: list[dict[str, Any]] = []
    warnings = list(state.get("warnings", []))
    for day in sorted(by_day):
        ordered = _best_order(by_day[day])
        offset = len(places)
        pairs = list(itertools.pairwise(ordered))
        with ThreadPoolExecutor(max_workers=6) as ex:
            day_legs = list(ex.map(lambda ab: get_route.route(ab[0]["lat"], ab[0]["lng"], ab[1]["lat"], ab[1]["lng"], transport), pairs))
        clock = req.get("start_time", "11:00")
        for i, p in enumerate(ordered):
            p = {**p, "order": i + 1, "day": day, "arrive": clock}
            places.append(p)
            if i < len(day_legs):
                leg = day_legs[i]
                legs.append({"from_idx": offset + i, "to_idx": offset + i + 1, **{k: leg[k] for k in ("transport", "duration_min", "distance_m", "polyline", "estimated")}})
                clock = _hhmm_add(clock, int(p.get("stay_min", 60)) + leg["duration_min"])
                if leg["estimated"] and leg["transport"] != "transit":
                    warnings.append(f"Day {day} {i + 1}→{i + 2} 구간은 길찾기 실패로 직선거리 추정")
            else:
                clock = _hhmm_add(clock, int(p.get("stay_min", 60)))
        if clock > req.get("end_time", "23:59") and places:
            warnings.append(f"Day {day} 일정이 종료 시각({req.get('end_time')})을 넘겨요 ({clock} 끝). 체류 시간을 줄여보세요")
    total_min = sum(leg["duration_min"] for leg in legs)
    detail = f"{len(places)}곳 {len(legs)}구간, 이동 총 {total_min}분"
    return {
        "places": places,
        "legs": legs,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "optimize_route", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _rag_review(name: str, region: str) -> str:
    """수집한 블로그 글 중 제목이 그 장소를 언급하는 글의 한 줄 요약. 없으면 빈 문자열."""
    head = search_place._norm_name(name.split()[0]) if name.split() else ""
    if len(head) < 3 or head.endswith(("맛집", "카페", "식당")):  # '송도맛집' 같은 일반 명사형 상호는 아무 글에나 걸린다
        return ""
    try:
        for d in rag.search(f"{region} {name}", region=region, k=4, doc_type="blog"):
            if d.get("one_line") and summarize_reviews.mentions(name, d.get("title") or ""):
                return str(d["one_line"])
    except Exception as e:  # noqa: BLE001
        log.debug("rag 리뷰 실패: %s", e)
    return ""


def enrich(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    req = state["request"]
    places = list(state.get("places", []))
    cond = ", ".join(req.get("moods") or []) + (f", {req['free_text']}" if req.get("free_text") else "")
    need = [i for i, p in enumerate(places) if not p.get("review_summary")]
    if need:
        summaries = summarize_reviews.summarize_many(
            [
                {"name": places[i]["name"], "region": req["region"],
                 "category": (places[i].get("kakao_category") or "").split(" > ")[-1] or places[i].get("category", "")}
                for i in need
            ],
            cond,
        )
        # 웹 리뷰가 비면 큐레이션 문서(RAG)의 한 줄 요약으로 대신한다 (제목에 그 장소명이 들어간 문서만)
        norm = search_place._norm_name
        one_lines = {
            norm(d.get("title") or ""): d["one_line"]
            for d in state.get("rag_docs", [])
            if d.get("doc_type") == "place" and d.get("one_line")  # 블로그 글의 한 줄은 다른 가게 얘기일 수 있어 쓰지 않는다
        }
        for i, s in zip(need, summaries, strict=True):
            s = "" if (not s or "부족" in s) else s
            if not s:
                s = one_lines.get(norm(places[i]["name"]), "")
            places[i] = {**places[i], "review_summary": s}
        # 그래도 비면 수집해 둔 블로그 글 중 제목이 그 장소를 언급하는 글의 한 줄 요약을 쓴다
        empty = [i for i in need if not places[i]["review_summary"]]
        if empty:
            with ThreadPoolExecutor(max_workers=min(6, len(empty))) as ex:
                found = list(ex.map(lambda i: _rag_review(places[i]["name"], req["region"]), empty))
            for i, s in zip(empty, found, strict=True):
                places[i] = {**places[i], "review_summary": s}
    n_ok = sum(1 for p in places if p.get("review_summary"))
    return {
        "places": places,
        "trace": state["trace"] + [{"node": "enrich", "status": "done", "ms": _now_ms() - t0, "detail": f"리뷰 요약 {n_ok}/{len(places)}"}],
    }


COMPOSE_SYSTEM = """당신은 Odiro. 확정된 코스를 사용자에게 친근하고 간결한 한국어 마크다운으로 안내합니다.

형식 (반드시 지킬 것)
- 첫 줄은 정확히 `**Odiro:**` 로 시작하고 코스를 한두 문장으로 소개.
- Day 가 여러 개일 때만 `### Day 1` 식 소제목. 하루 코스면 소제목 없음.
- 장소는 번호 목록. 각 항목: `**장소명** (도착 HH:MM · 체류 N분) — 추천 이유.` 리뷰가 있으면 뒤에 ` 💬 리뷰 한 줄` (리뷰가 '-' 이거나 없으면 💬 부분 생략).
  다음 장소까지 이동은 들여쓴 줄 `↳ 🚶 도보 12분 (900m)` / `🚌 대중교통 약 25분` / `🚗 자차 19분 (10.9km)`.
- 마지막에 `**팁**` 한두 줄: 날씨·일몰·예산·웨이팅 중 조건과 관련된 것만.
- 주어진 정보 밖의 사실(영업시간, 가격 등)을 지어내지 않는다. 장소명은 주어진 그대로 쓴다."""


def _fallback_answer(state: dict[str, Any]) -> str:
    req = state["request"]
    lines = [f"**Odiro:** {req['region']} 코스를 준비했어요."]
    cur_day = None
    legs = {leg["from_idx"]: leg for leg in state.get("legs", [])}
    for i, p in enumerate(state.get("places", [])):
        if p["day"] != cur_day:
            cur_day = p["day"]
            if req.get("mode") == "trip":
                lines.append(f"\n### Day {cur_day}")
        line = f"{p['order']}. **{p['name']}** ({p.get('arrive', '')} · {p.get('stay_min', 60)}분) — {p.get('reason', '')}"
        if p.get("review_summary"):
            line += f" 💬 {p['review_summary']}"
        lines.append(line)
        if i in legs:
            leg = legs[i]
            icon = {"walk": "🚶 도보", "transit": "🚌 대중교통", "car": "🚗 자차"}[leg["transport"]]
            lines.append(f"   ↳ {icon} {'약 ' if leg['estimated'] else ''}{leg['duration_min']}분 ({leg['distance_m'] / 1000:.1f}km)")
    if state.get("warnings"):
        lines.append("\n**참고** " + " / ".join(state["warnings"]))
    return "\n".join(lines)


def compose_answer(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    if not state.get("places"):
        return {
            "final_answer": "**Odiro:** 조건에 맞는 장소를 지도에서 확인하지 못했어요. 지역을 조금 넓히거나 분위기 태그를 줄여서 다시 시도해 주세요.",
            "trace": state["trace"] + [{"node": "compose_answer", "status": "skip", "ms": 0, "detail": "장소 없음"}],
        }
    req = state["request"]
    legs = {leg["from_idx"]: leg for leg in state.get("legs", [])}
    rows = []
    for i, p in enumerate(state["places"]):
        row = f"Day{p['day']} #{p['order']} {p['name']} | {p.get('category')} | 도착 {p.get('arrive')} 체류 {p.get('stay_min')}분 | 이유: {p.get('reason')} | 리뷰: {p.get('review_summary') or '-'} | 태그: {', '.join(p.get('tags') or [])}"
        if i in legs:
            leg = legs[i]
            row += f" | 다음까지: {leg['transport']} {leg['duration_min']}분 {leg['distance_m']}m{' (추정)' if leg['estimated'] else ''}"
        rows.append(row)
    wx, sun = state.get("weather") or {}, state.get("sun_times") or {}
    ctx = (
        f"## 조건\n{state['conditions']}\n\n## 코스 제목\n{state.get('title', '')}\n\n## 확정 코스\n" + "\n".join(rows)
        + f"\n\n## 날씨\n{wx if wx.get('available') else '예보 없음'}\n## 일출/일몰\n{sun.get('sunrise')} / {sun.get('sunset')}"
        + ("\n## 참고사항\n" + "\n".join(state["warnings"]) if state.get("warnings") else "")
    )
    try:
        out = chat(0.5).invoke([("system", COMPOSE_SYSTEM), ("human", ctx)])
        text = str(out.content).strip()
        if not text.startswith("**Odiro:**"):
            text = "**Odiro:** " + text
        if req.get("mode") != "trip":  # 나들이는 Day 소제목 불필요
            text = "\n".join(ln for ln in text.splitlines() if not ln.strip().lower().startswith("### day"))
    except Exception as e:  # noqa: BLE001
        log.warning("compose 실패 → 템플릿: %s", e)
        text = _fallback_answer(state)
    return {
        "final_answer": text,
        "trace": state["trace"] + [{"node": "compose_answer", "status": "done", "ms": _now_ms() - t0, "detail": f"{len(text)}자"}],
    }


# ---------- 수정 플라이휠 ----------

MODIFY_SYSTEM = DRAFT_SYSTEM + """

지금은 **기존 코스의 한 장소만 교체**하는 단계입니다. 사용자의 수정 요청을 읽고 어느 장소(인덱스)를 무엇으로 바꿀지 정하세요.
- target_number 는 '현재 코스' 목록에 적힌 번호 그대로입니다 (1부터). "N번째" 는 N번, "마지막" 은 맨 끝 번호.
- 비 예보가 있으면 교체 장소는 실내로 고릅니다.
- alternates 에는 place 가 지도에 없을 때를 대비해 같은 요청을 만족하는 다른 실존 장소 2~3개를 넣습니다.
- keywords 에는 새 장소의 업종을 지도 앱 검색어로 2~3개 넣습니다 (예: 실내 놀이공간 → "키즈카페", "실내놀이터"). 이름을 못 찾으면 이 검색어로 근처 실존 장소를 찾습니다.
- 교체 장소는 같은 지역·같은 역할에서 요청한 성격(더 조용한, 실내, 저렴한 등)을 만족하는 **실존 장소**. 기존 코스의 다른 장소와 가까울수록 좋습니다.
- name 은 지도에 등록된 상호 그대로만 ("성수동 애견동반카페 따우전드" ✗ → "따우전드 성수" ✓). 수식어·지역명을 붙이지 않습니다.
- 코스 전체를 다시 짜달라는 요청이면 target_number=0, place=null."""


def modify(state: dict[str, Any]) -> dict[str, Any]:
    """edit 흐름의 첫 노드. state 에 places/legs(기존 코스), instruction, target_index 가 들어온다."""
    t0 = _now_ms()
    places = list(state.get("places", []))
    instruction = state.get("instruction", "")
    target = state.get("target_index")
    if target is None:
        target = _parse_target(instruction, places)  # "3번째", "마지막" 은 LLM 에 맡기지 않고 확정
    wx = state.get("weather") or {}
    listing = "\n".join(f"- {i + 1}번: Day{p['day']} {p['name']} ({p.get('category')}) — {p.get('reason', '')}" for i, p in enumerate(places))
    prompt = (
        f"## 조건\n{state['conditions']}"
        + (f"\n날씨: 비 예보 (강수확률 {int((wx.get('pop') or 0) * 100)}%)" if wx.get("rain") else "")
        + f"\n\n## 현재 코스\n{listing}\n\n## 수정 요청\n{instruction}"
        + (f"\n(바꿀 대상은 {target + 1}번으로 확정)" if target is not None else "")
        + f"\n\n## 참고 문서\n{_fmt_rag_docs(state.get('rag_docs', []), 8)}"
    )
    try:
        plan: EditPlan = chat(0.5).with_structured_output(EditPlan).invoke([("system", MODIFY_SYSTEM), ("human", prompt)])
    except Exception as e:  # noqa: BLE001
        return {
            "candidates": places,
            "spares": [],
            "edit_note": f"수정 요청을 이해하지 못했어요 ({str(e)[:40]})",
            "trace": state.get("trace", []) + [{"node": "modify", "status": "error", "ms": _now_ms() - t0, "detail": str(e)[:80]}],
        }
    idx = target if target is not None else plan.target_number - 1
    if plan.place is None or idx < 0 or idx >= len(places):
        return {
            "candidates": [],
            "spares": [],
            "rejected": [p["name"] for p in places],
            "edit_note": plan.note or "코스를 새로 구성합니다",
            "full_redraft": True,
            "trace": state.get("trace", []) + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": "전체 재구성"}],
        }
    old = places[idx]
    new = {**plan.place.model_dump(), "day": old["day"], "order": old["order"], "verified": False}
    cands = [{**p} for p in places]
    cands[idx] = new
    spares = [{**a.model_dump(), "day": old["day"], "order": 0, "verified": False} for a in plan.alternates[:3]]
    # LLM 이 고른 이름이 전부 지도에 없을 때를 대비해, 같은 업종의 실존 장소를 원래 자리 근처에서 찾아 마지막 예비로 둔다
    n_nearby = 0
    keywords = [k.strip() for k in plan.keywords if k.strip()][:3]
    rest = [p for i, p in enumerate(places) if i != idx and p["day"] == old["day"] and p.get("lat")] or [old]
    near = {"lat": sum(p["lat"] for p in rest) / len(rest), "lng": sum(p["lng"] for p in rest) / len(rest)}
    if keywords and near["lat"]:
        try:
            radius = WALK_OUTLIER_M if state["request"].get("transport") == "walk" else 8000
            taken = {p.get("kakao_place_id") for p in places}
            found: list[tuple[str, dict[str, Any]]] = []
            for kw in keywords:
                for h in search_place.search(kw, near["lat"], near["lng"], radius, size=10):
                    if h.get("kakao_place_id") not in taken:
                        taken.add(h.get("kakao_place_id"))
                        found.append((kw, h))
                if len(found) >= 3:
                    break
            for kw, h in found[:3]:
                spares.append({
                    **plan.place.model_dump(), "name": h["name"], "reason": f"요청하신 조건({kw})으로 근처에서 찾은 곳",
                    "source": "rag", "day": old["day"], "order": 0, "verified": True, "lat": h["lat"], "lng": h["lng"],
                    "address": h.get("address", ""), "kakao_place_id": h.get("kakao_place_id", ""), "place_url": h.get("place_url", ""),
                    "phone": h.get("phone", ""), "kakao_category": h.get("category_full", ""),
                })
                n_nearby += 1
        except Exception as e:  # noqa: BLE001
            log.warning("수정 후보 주변 검색 실패: %s", e)
    return {
        "candidates": cands,
        "spares": spares,
        "rejected": list(state.get("rejected", [])) + [old["name"]],
        "edit_slot": {"index": idx, "old": old, "planned": new["name"]},
        "edit_note": f"{old['name']} → {new['name']}",  # verify_places 가 실제로 들어간 장소 기준으로 다시 쓴다
        "trace": state.get("trace", [])
        + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": f"{idx + 1}번 {old['name']} 교체 후보: {new['name']} (+대안 {len(spares) - n_nearby}, 주변 검색 {n_nearby})"}],
    }
