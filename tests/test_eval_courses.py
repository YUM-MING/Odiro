"""scripts/eval_courses.py 의 지표 계산 (네트워크·LLM 없음)."""

import importlib.util
from pathlib import Path

from odiro.api.schemas import CourseRequest, CourseResponse, PlaceOut

_spec = importlib.util.spec_from_file_location("eval_courses", Path(__file__).resolve().parent.parent / "scripts" / "eval_courses.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

CENTER = {"lat": 37.5446, "lng": 127.0557}


def _p(order, name, cat, day=1, lat=37.5446, lng=127.0557, pid="1", verified=True):
    return PlaceOut(order=order, day=day, name=name, category=cat, lat=lat, lng=lng, kakao_place_id=pid, verified=verified)


def _resp(places, budget=100_000):
    r = CourseResponse(
        course_id="c", request=CourseRequest(region="성수동", date="2026-11-20", budget=budget), places=places, legs=[], answer_md=""
    )
    r.meta.est_cost_total = 50_000
    return r


def test_clean_course():
    m = ev.evaluate(_resp([_p(1, "a", "관광지"), _p(2, "b", "식당"), _p(3, "c", "카페")]), CENTER, 1500)
    assert m["unverified"] == 0 and m["outside"] == 0 and m["comp_ok"] and not m["over_budget"]
    assert ev.comp_text(m["comp"]) == "D1 식1·카1·볼1"


def test_unverified_detected():
    places = [_p(1, "a", "식당"), _p(2, "b", "카페", pid=""), _p(3, "c", "관광지", verified=False)]
    m = ev.evaluate(_resp(places), CENTER, 1500)
    assert m["unverified"] == 2 and m["unverified_names"] == ["b", "c"]


def test_outside_radius_ratio():
    far = _p(2, "far", "카페", lat=37.60)  # 약 6km
    m = ev.evaluate(_resp([_p(1, "near", "식당"), far]), CENTER, 1500)
    assert m["outside"] == 1 and m["outside_ratio"] == 0.5


def test_lacking_day_and_lodging_ignored():
    places = [_p(1, "a", "식당"), _p(2, "b", "카페"), _p(1, "c", "관광지", day=2), _p(2, "hotel", "숙소", day=2)]
    m = ev.evaluate(_resp(places, budget=10_000), CENTER, 1500)
    assert m["days_lacking"] == [2] and not m["comp_ok"] and m["over_budget"]
    assert "⚠구성 미흡" in ev.render_table({"x": m})


def test_table_handles_error_and_compare():
    ok = ev.evaluate(_resp([_p(1, "a", "식당"), _p(2, "b", "카페")]), CENTER, 1500)
    table = ev.render_table({"ok": ok, "bad": {"error": "boom", "elapsed_s": 1.0}})
    assert "실패: boom" in table and "1/2 성공" in table
    assert "(비교 불가)" in ev.render_compare({"bad": {"error": "x"}}, {"bad": {"error": "x"}})
    worse = {**ok, "outside_ratio": 0.5, "elapsed_s": 99.0}
    assert "0% → 50%" in ev.render_compare({"ok": ok}, {"ok": worse})


def test_scenarios_are_valid_requests():
    assert len(ev.SCENARIOS) == 10
    for cfg in ev.SCENARIOS.values():
        CourseRequest(date="2026-11-20", **cfg)
