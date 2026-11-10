"""그래프 실행기 + CLI.

- run_course(request, on_progress)  : CourseRequest → CourseResponse. 노드마다 on_progress(TraceStep) 호출 (SSE 용)
- run_edit(edit, on_progress)       : EditRequest → CourseResponse
- 결과 캐시: 요청 해시 → diskcache 7일 (시연 안정성. 같은 조건이면 네트워크 없이 같은 결과)

CLI:
    python -m odiro.agent.run "성수동" --moods 감성/조용한 사진맛집 --date 2026-11-15
    python -m odiro.agent.run "가평" --mode trip --days 2 --transport car --json
"""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from odiro.agent.graph import EDIT_SEQUENCE, MAIN_SEQUENCE, build_edit_graph, build_graph
from odiro.api.schemas import (
    CourseMeta,
    CourseRequest,
    CourseResponse,
    EditRequest,
    LegOut,
    PlaceOut,
    SunOut,
    TraceStep,
    WeatherOut,
)
from odiro.tools._util import cache, cache_key

log = logging.getLogger("odiro.agent")
Progress = Callable[[TraceStep], None]
COURSE_CACHE_TTL = 7 * 24 * 3600

_graph = None
_edit_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def edit_graph():
    global _edit_graph
    if _edit_graph is None:
        _edit_graph = build_edit_graph()
    return _edit_graph


def _to_response(state: dict[str, Any], req: CourseRequest, elapsed_ms: int, cached: bool = False) -> CourseResponse:
    places = [
        PlaceOut(
            order=p["order"], day=p.get("day", 1), name=p["name"], category=p.get("category", ""),
            lat=p["lat"], lng=p["lng"], address=p.get("address", ""), kakao_place_id=p.get("kakao_place_id", ""),
            place_url=p.get("place_url", ""), phone=p.get("phone", ""), reason=p.get("reason", ""),
            tags=p.get("tags") or [], review_summary=p.get("review_summary", ""), arrive=p.get("arrive", ""),
            stay_min=int(p.get("stay_min", 60)), image=p.get("image", ""), verified=True, source=p.get("source", ""),
        )
        for p in state.get("places", [])
        if p.get("verified")
    ]
    legs = [LegOut(**leg) for leg in state.get("legs", [])]
    wx = state.get("weather") or {}
    sun = state.get("sun_times") or {}
    meta = CourseMeta(
        sun=SunOut(sunrise=sun.get("sunrise", ""), sunset=sun.get("sunset", "")),
        weather=WeatherOut(
            available=bool(wx.get("available")), summary=wx.get("summary", ""), temp_c=wx.get("temp_c"),
            pop=wx.get("pop"), rain=bool(wx.get("rain")), note=wx.get("note", ""),
        ),
        rag_docs=len(state.get("rag_docs", [])),
        web_docs=len(state.get("web_docs", [])),
        warnings=list(dict.fromkeys(state.get("warnings", []))),
        trace=[TraceStep(**t) for t in state.get("trace", [])],
        cached=cached,
        elapsed_ms=elapsed_ms,
    )
    answer = state.get("final_answer", "")
    if state.get("edit_note"):
        answer = f"_{state['edit_note']}_\n\n{answer}"
    return CourseResponse(
        course_id=f"c_{uuid.uuid4().hex[:10]}", request=req, title=state.get("title", ""),
        places=places, legs=legs, answer_md=answer, meta=meta,
    )


def _stream(g, state: dict[str, Any], sequence: tuple[str, ...], on_progress: Progress | None) -> dict[str, Any]:
    """graph.stream 으로 노드별 업데이트를 받아 진행 이벤트를 쏘고, 최종 상태를 합쳐 돌려준다."""
    merged = dict(state)
    if on_progress:
        on_progress(TraceStep(node=sequence[0], status="start"))
    for update in g.stream(state, stream_mode="updates"):
        for node, delta in update.items():
            merged.update(delta)
            if on_progress:
                steps = [t for t in delta.get("trace", []) if t.get("node") == node]
                on_progress(TraceStep(**steps[-1]) if steps else TraceStep(node=node, status="done"))
                # 다음 노드 start 알림 (수정 그래프의 분기 포함)
                nxt = None
                if node == "modify":
                    nxt = "draft_course" if delta.get("full_redraft") else "verify_places"
                elif node in sequence and sequence.index(node) + 1 < len(sequence):
                    nxt = sequence[sequence.index(node) + 1]
                elif node == "draft_course" and "modify" in sequence:
                    nxt = "verify_places"
                if nxt:
                    on_progress(TraceStep(node=nxt, status="start"))
    return merged


def run_course(req: CourseRequest, on_progress: Progress | None = None, use_cache: bool = True) -> CourseResponse:
    t0 = time.time()
    key = cache_key("course", req.model_dump())
    if use_cache:
        hit = cache().get(key)
        if hit:
            resp = CourseResponse.model_validate(hit)
            if on_progress:
                for step in MAIN_SEQUENCE:
                    on_progress(TraceStep(node=step, status="done", ms=0, detail="캐시"))
            resp.meta.cached = True
            resp.course_id = f"c_{uuid.uuid4().hex[:10]}"
            return resp
    state: dict[str, Any] = {"request": req.model_dump(), "trace": [], "warnings": []}
    final = _stream(graph(), state, MAIN_SEQUENCE, on_progress)
    resp = _to_response(final, req, int((time.time() - t0) * 1000))
    if resp.places and use_cache:
        cache().set(key, resp.model_dump(), expire=COURSE_CACHE_TTL)
    return resp


def run_edit(edit: EditRequest, on_progress: Progress | None = None) -> CourseResponse:
    t0 = time.time()
    course = edit.course
    req = course.request
    places = [
        {**p.model_dump(), "verified": True} for p in course.places
    ]
    target_index = None
    if edit.target_order is not None:
        for i, p in enumerate(places):
            if p["order"] == edit.target_order and p["day"] == edit.target_day:
                target_index = i
                break
    # parse_intent/retrieve 를 다시 돌리지 않으려고 필요한 컨텍스트를 직접 채운다
    from odiro.agent import nodes
    from odiro.tools import rag_search, search_place

    center = None
    try:
        center = search_place.geocode_region(req.region)
    except Exception as e:  # noqa: BLE001
        log.debug("geocode 실패: %s", e)
    rag_docs: list[dict[str, Any]] = []
    try:
        rag_docs = rag_search.search(f"{req.region} {edit.instruction}", moods=req.moods, region=req.region, k=8)
    except Exception as e:  # noqa: BLE001
        log.debug("rag 실패: %s", e)
    state: dict[str, Any] = {
        "request": req.model_dump(),
        "center": center,
        "conditions": nodes._conditions_text(req.model_dump()),
        "per_day": nodes._places_per_day(req.model_dump()),
        "rag_docs": rag_docs,
        "web_docs": [],
        "weather": {"available": False, "rain": course.meta.weather.rain, "summary": course.meta.weather.summary, "pop": course.meta.weather.pop, "note": ""},
        "sun_times": {"sunrise": course.meta.sun.sunrise, "sunset": course.meta.sun.sunset},
        "title": course.title,
        "places": places,
        "legs": [leg.model_dump() for leg in course.legs],
        "instruction": edit.instruction,
        "target_index": target_index,
        "trace": [],
        "warnings": [],
        "rejected": [],
    }
    final = _stream(edit_graph(), state, EDIT_SEQUENCE, on_progress)
    return _to_response(final, req, int((time.time() - t0) * 1000))


# ---------- CLI ----------


def _next_saturday() -> str:
    d = date.today()
    return (d + timedelta(days=(5 - d.weekday()) % 7 or 7)).isoformat()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("region")
    ap.add_argument("--mode", choices=["outing", "trip"], default="outing")
    ap.add_argument("--transport", choices=["walk", "car"], default="walk")
    ap.add_argument("--date", default=_next_saturday())
    ap.add_argument("--start", default="11:00")
    ap.add_argument("--end", default="20:00")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--budget", type=int, default=100_000)
    ap.add_argument("--moods", nargs="*", default=[])
    ap.add_argument("--text", default="")
    ap.add_argument("--party", default="")
    ap.add_argument("--edit", default=None, help="생성 후 이어서 수정 요청 한 번 실행. 예) '2번째를 실내로 바꿔줘'")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--json", action="store_true", help="CourseResponse JSON 출력")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    req = CourseRequest(
        mode=args.mode, transport=args.transport, region=args.region, date=args.date, start_time=args.start,
        end_time=args.end, days=args.days, budget=args.budget, moods=args.moods, free_text=args.text, party=args.party,
    )

    def progress(step: TraceStep) -> None:
        if step.status != "start":
            print(f"  ✓ {step.node:<16} {step.ms:>6}ms  {step.detail}")

    resp = run_course(req, progress, use_cache=not args.no_cache)
    if args.edit:
        print(f"\n--- 수정: {args.edit}")
        resp = run_edit(EditRequest(course=resp, instruction=args.edit), progress)
    if args.json:
        print(resp.model_dump_json(indent=2, exclude={"legs": {"__all__": {"polyline"}}}))
        return
    print(f"\n# {resp.title}  ({resp.meta.elapsed_ms / 1000:.1f}s{', 캐시' if resp.meta.cached else ''})")
    print(resp.answer_md)
    print("\n장소:")
    for p in resp.places:
        print(f"  D{p.day}-{p.order} {p.name} [{p.category}] ({p.lat:.5f},{p.lng:.5f}) {p.address} {p.place_url}")
    if resp.meta.warnings:
        print("경고:", resp.meta.warnings)


if __name__ == "__main__":
    main()
