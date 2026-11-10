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


# ---------- LLM 출력 스키마 ----------


class DraftPlace(BaseModel):
    name: str = Field(description="실제 존재하는 구체적 상호/장소명. 체인점이면 지점명까지. 예) '어니언 성수', '서울숲'")
    category: Literal["식당", "카페", "관광지", "놀거리", "산책", "쇼핑", "숙소", "기타"]
    reason: str = Field(description="이 조건에 왜 맞는지 1문장 (근거 문서가 있으면 그 내용으로)")
    stay_min: int = Field(60, ge=20, le=180)
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
    target_index: int = Field(description="바꿀 장소의 places 인덱스 (0부터). 전체 재구성 요청이면 -1")
    place: DraftPlace | None = Field(None, description="target_index 자리에 넣을 새 장소. 전체 재구성이면 null")
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


def _fmt_rag_docs(docs: list[dict[str, Any]], limit: int = 12) -> str:
    lines = []
    for d in docs[:limit]:
        if d.get("doc_type") == "place":
            lines.append(f"- [장소 ✔지도확인] {d.get('title')} ({d.get('content_type', '')}, {d.get('addr', '')}) — {d.get('one_line') or ''} {d.get('tags') or ''}")
        else:
            lines.append(f"- [블로그] {d.get('title')} — {d.get('one_line') or d.get('snippet', '')[:120]} {d.get('tags') or ''}")
    return "\n".join(lines) or "- (없음)"


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
            places = rag.search(base_q, moods=moods, region=req["region"], k=10, doc_type="place")
            blogs = rag.search(base_q, moods=moods, region=req["region"], k=8, doc_type="blog")
            return places + blogs
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

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_rag, f_web, f_wx, f_sun = ex.submit(do_rag), ex.submit(do_web), ex.submit(do_weather), ex.submit(do_sun)
        rag_docs, web_docs, weather, sun = f_rag.result(), f_web.result(), f_wx.result(), f_sun.result()

    warnings = list(state.get("warnings", []))
    if weather.get("rain"):
        warnings.append(f"비 예보(강수확률 {int((weather.get('pop') or 0) * 100)}%) → 실내 위주로 구성했어요")
    detail = f"RAG {len(rag_docs)}건 / 웹 {len(web_docs)}건 / 날씨 {weather.get('summary') or weather.get('note', '-')}"
    return {
        "rag_docs": rag_docs,
        "web_docs": web_docs,
        "weather": weather,
        "sun_times": sun,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "retrieve", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


DRAFT_SYSTEM = """당신은 Odiro, 국내 여행·데이트 코스 플래너입니다. 사용자 조건에 맞는 코스를 JSON 으로 설계합니다.

원칙
1. **실제로 존재하는 구체적인 장소명만** 씁니다. 모호한 표현("성수동 감성 카페")이나 지어낸 상호는 금지. 확신이 없으면 유명한 곳을 고릅니다.
   장소명은 지도 앱에 등록된 공식 명칭으로 (예: "가평레일파크", "쁘띠프랑스", "어니언 성수").
2. 제공된 큐레이션 문서 중 **[장소 ✔지도확인]** 표시가 있는 것은 실존이 확인된 장소이니 조건에 맞으면 우선 사용하고 source="rag" 로 표기합니다.
   블로그 글에 나온 상호를 쓰면 source="rag", 웹검색은 "web", 일반 지식은 "llm".
3. 나들이 모드 기본 뼈대는 "밥 1 + 카페 1 + 놀거리/산책 1 (+α)". 여행 모드는 Day 별로, 마지막 Day 를 제외하고 숙소를 마지막에 둡니다.
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
        f"## 웹 검색\n{_fmt_web_docs(state.get('web_docs', []))}",
        f"## 요구 구조\nDay 수: {days}, Day 당 장소 {per_day}개 (정확히) + 예비 {SPARES_PER_DAY}개. 방문 순서대로.",
    ]
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
    for d in draft.days:
        for i, p in enumerate(d.places[:cap], 1):
            cands.append({**p.model_dump(), "day": d.day, "order": i, "verified": False})
        for p in d.spares[:SPARES_PER_DAY + 1]:
            spares.append({**p.model_dump(), "day": d.day, "order": 0, "verified": False})
    detail = f"{len(cands)}곳 초안 + 예비 {len(spares)} ({sum(1 for c in cands if c['source'] == 'rag')} RAG 근거)"
    return {
        "candidates": cands,
        "spares": spares,
        "title": draft.title,
        "trace": state["trace"] + [{"node": "draft_course", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _verify_one(c: dict[str, Any], center: dict[str, Any] | None, radius: int, hint: str) -> dict[str, Any]:
    if c.get("verified") and c.get("lat") and c.get("lng"):
        return c  # 수정 흐름에서 이미 검증된 장소
    hit = None
    try:
        if center:
            hit = search_place.verify(c["name"], center["lat"], center["lng"], radius, hint)
        else:
            res = search_place.search(f"{hint} {c['name']}", size=3)
            hit = res[0] if res else None
    except Exception as e:  # noqa: BLE001
        log.warning("verify 오류 %s: %s", c["name"], e)
    if not hit:
        return {**c, "verified": False}
    cat = c.get("category") or ""
    group = hit.get("category_group", "")
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
    hint = req["region"]
    cands = list(state.get("candidates", []))
    spares = list(state.get("spares", []))
    rejected: list[str] = list(state.get("rejected", []))

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda c: _verify_one(c, center, radius, hint), cands + spares))
    cands, spares = results[: len(cands)], results[len(cands) :]
    used_ids = {c.get("kakao_place_id") for c in cands if c["verified"]}
    spare_pool = [s for s in spares if s["verified"] and s.get("kakao_place_id") not in used_ids]

    def fill_from_spares() -> None:
        for i, c in enumerate(cands):
            if c["verified"]:
                continue
            pick = next((s for s in spare_pool if s["day"] == c["day"] and _same_role(s["category"], c["category"])), None) or next(
                (s for s in spare_pool if s["day"] == c["day"]), None
            )
            if pick:
                spare_pool.remove(pick)
                rejected.append(c["name"])
                cands[i] = {**pick, "order": c["order"], "day": c["day"]}

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
            + "\n".join(f"- 슬롯 {i}: Day {cands[i]['day']} {cands[i]['order']}번째, 역할 {cands[i]['category']}, 원래 제안 '{cands[i]['name']}'" for i in missing)
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
        fill_from_spares()

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
    warnings = list(state.get("warnings", []))
    dropped = len(cands) - len(verified)
    if dropped:
        warnings.append(f"지도에서 확인되지 않은 장소 {dropped}곳을 제외했어요")
    detail = f"{len(verified)}/{len(cands)} 확인 (예비 {len(spares) - len(spare_pool)}개 사용, LLM 보충 {rounds}회)"
    return {
        "verified": verified,
        "rejected": rejected,
        "retry_count": rounds,
        "warnings": warnings,
        "trace": state["trace"] + [{"node": "verify_places", "status": "done", "ms": _now_ms() - t0, "detail": detail}],
    }


def _best_order(places: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLM 순서를 기본으로 하되, 순열 전수로 총거리가 25% 이상 줄면 그 순서를 쓴다 (n ≤ 6)."""
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


def enrich(state: dict[str, Any]) -> dict[str, Any]:
    t0 = _now_ms()
    req = state["request"]
    places = list(state.get("places", []))
    cond = ", ".join(req.get("moods") or []) + (f", {req['free_text']}" if req.get("free_text") else "")
    need = [i for i, p in enumerate(places) if not p.get("review_summary")]
    if need:
        summaries = summarize_reviews.summarize_many([{"name": places[i]["name"], "region": req["region"]} for i in need], cond)
        for i, s in zip(need, summaries, strict=True):
            places[i] = {**places[i], "review_summary": "" if (not s or "부족" in s) else s}
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
- 요청이 특정 장소를 가리키면 그 인덱스, "N번째" 는 N-1.
- 교체 장소는 같은 지역·같은 역할에서 요청한 성격(더 조용한, 실내, 저렴한 등)을 만족하는 **실존 장소**. 기존 코스의 다른 장소와 가까울수록 좋습니다.
- 코스 전체를 다시 짜달라는 요청이면 target_index=-1, place=null."""


def modify(state: dict[str, Any]) -> dict[str, Any]:
    """edit 흐름의 첫 노드. state 에 places/legs(기존 코스), instruction, target_index 가 들어온다."""
    t0 = _now_ms()
    places = list(state.get("places", []))
    instruction = state.get("instruction", "")
    target = state.get("target_index")
    listing = "\n".join(f"- [{i}] Day{p['day']} #{p['order']} {p['name']} ({p.get('category')}) — {p.get('reason', '')}" for i, p in enumerate(places))
    prompt = (
        f"## 조건\n{state['conditions']}\n\n## 현재 코스\n{listing}\n\n## 수정 요청\n{instruction}"
        + (f"\n(사용자가 지정한 대상 인덱스: {target})" if target is not None else "")
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
    idx = target if target is not None else plan.target_index
    if plan.place is None or idx is None or idx < 0 or idx >= len(places):
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
    return {
        "candidates": cands,
        "spares": [],
        "rejected": list(state.get("rejected", [])) + [old["name"]],
        "edit_note": plan.note or f"{old['name']} → {new['name']}",
        "trace": state.get("trace", []) + [{"node": "modify", "status": "done", "ms": _now_ms() - t0, "detail": f"[{idx}] {old['name']} → {new['name']}"}],
    }
