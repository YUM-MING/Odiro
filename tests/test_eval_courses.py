"""scripts/eval_courses.py 의 지표 계산 (네트워크·LLM 없음)."""

import importlib.util
import json
from datetime import datetime
from pathlib import Path

from odiro.api.schemas import CourseRequest, CourseResponse, PlaceOut

_spec = importlib.util.spec_from_file_location("eval_courses", Path(__file__).resolve().parent.parent / "scripts" / "eval_courses.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

CENTER = {"lat": 37.5446, "lng": 127.0557}


def _p(order, name, cat, day=1, lat=37.5446, lng=127.0557, pid="1", verified=True, **kw):
    return PlaceOut(order=order, day=day, name=name, category=cat, lat=lat, lng=lng, kakao_place_id=pid, verified=verified, **kw)


def _resp(places, budget=100_000, end_time="20:00"):
    r = CourseResponse(
        course_id="c", request=CourseRequest(region="성수동", date="2026-11-20", budget=budget, end_time=end_time), places=places, legs=[], answer_md=""
    )
    r.meta.est_cost_total = 50_000
    return r


def test_clean_course():
    m = ev.evaluate(_resp([_p(1, "a", "관광지"), _p(2, "b", "식당"), _p(3, "c", "카페")]), CENTER, 1500)
    assert m["unverified"] == 0 and m["outside"] == 0 and m["comp_ok"] and not m["over_budget"]
    assert ev.comp_text(m["comp"]) == "D1 식1·카1·볼1"


def test_unverified_detected():
    places = [_p(1, "a", "식당"), _p(2, "b", "카페", lat=0), _p(3, "c", "관광지", verified=False)]
    m = ev.evaluate(_resp(places), CENTER, 1500)
    assert m["unverified"] == 2 and m["unverified_names"] == ["b", "c"]


def test_missing_kakao_id_is_not_unverified():
    # TourAPI 큐레이션 장소는 카카오 ID 없이 verified=True 로 들어간다 → 미확인으로 세지 않는다
    m = ev.evaluate(_resp([_p(1, "a", "관광지", pid=""), _p(2, "b", "식당"), _p(3, "c", "카페")]), CENTER, 1500)
    assert m["unverified"] == 0


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


def test_overtime_uses_last_non_lodging_place_end():
    places = [_p(1, "a", "식당", arrive="18:00", stay_min=60), _p(2, "b", "카페", arrive="19:30", stay_min=60), _p(3, "hotel", "숙소", arrive="21:00", stay_min=60)]
    assert ev.overtime(places, "20:00") == {1: 30}  # b 가 20:30 에 끝남. 숙소는 보지 않는다
    assert ev.overtime(places, "20:30") == {}  # 딱 맞으면 초과 아님
    m = ev.evaluate(_resp(places, end_time="20:00"), CENTER, 1500)
    assert m["overtime"] == {"1": 30} and m["overtime_max_min"] == 30
    assert "D1 +30분" in ev.render_table({"x": m})


def test_overtime_handles_past_midnight_and_missing_arrive():
    places = [_p(1, "a", "식당", arrive="23:30", stay_min=60), _p(1, "b", "카페", day=2), _p(2, "c", "카페", day=2, arrive="24:10", stay_min=30)]
    assert ev.overtime(places, "23:59") == {1: 31, 2: 41}  # '24:10' 처럼 자정을 넘긴 표기도 읽는다
    assert ev.overtime([_p(1, "x", "식당")], "20:00") == {}  # 도착 시각이 없으면 건너뜀


def test_scenarios_are_valid_requests():
    assert len(ev.SCENARIOS) == 11
    for cfg in ev.SCENARIOS.values():
        CourseRequest(date="2026-11-20", **cfg)


def test_gapyeong_preset_matches_site_preset_defaults():
    # 사이트 "# 가평 1박 2일" = defaultRequest() + PRESETS patch (frontend/src/request.ts). 날짜만 --date 로 바뀐다
    req = CourseRequest(date="2026-11-26", **ev.SCENARIOS["gapyeong_preset"])
    assert (req.mode, req.transport, req.region, req.days) == ("trip", "car", "가평", 2)
    assert (req.start_time, req.end_time, req.budget, req.headcount) == ("11:00", "20:00", 100_000, 1)
    assert req.moods == ["자연/산책", "뷰맛집/일몰"] and req.party == "연인" and req.free_text == "" and req.lodging == ""
    assert ev.SCENARIOS["gapyeong_trip"]["start_time"] == "10:00"  # 기존 시나리오는 그대로


# ---------- 중복 의심 · 분류 의심 · 경고 문구 ----------


def test_same_shop_with_spacing_difference_is_duplicate():
    # 11/22 가평 재현: TourAPI 좌표의 "카페 드 모파상"(관광지) + 카카오 좌표의 "카페드모파상"(식당), 약 22m
    places = [
        _p(1, "카페 드 모파상", "관광지", lat=37.7013794825, lng=127.3963235444, pid=""),
        _p(2, "카페드모파상", "식당", lat=37.70124550237815, lng=127.3961320593873),
        _p(3, "청평호반", "관광지", lat=37.73, lng=127.42),
    ]
    m = ev.evaluate(_resp(places), CENTER, 30_000)
    assert m["dup_suspects"] == 1
    pair = m["dup_pairs"][0]
    assert {pair["a"], pair["b"]} == {"카페 드 모파상", "카페드모파상"} and 15 <= pair["dist_m"] <= 30
    assert {pair["a_category"], pair["b_category"]} == {"관광지", "식당"}


def test_different_shops_30m_apart_are_not_duplicate():
    # 좌표만으로는 판정하지 않는다: 같은 건물의 다른 매장
    places = [_p(1, "로우키커피", "카페", lat=37.5446, lng=127.0557), _p(2, "하노이별", "식당", lat=37.54487, lng=127.0557)]
    m = ev.evaluate(_resp(places), CENTER, 1500)
    assert m["dup_suspects"] == 0


def test_same_name_rules_and_thresholds():
    # 정규화 이름 일치는 150m 까지, 비슷한 이름(유사도 ≥ 0.85)은 50m 까지
    assert ev.same_place("서울숲", 37.5444, 127.0374, "서울 숲", 37.5444 + 0.0012, 127.0374)[0]  # 약 133m, 이름 같음
    assert not ev.same_place("서울숲", 37.5444, 127.0374, "서울 숲", 37.5444 + 0.0018, 127.0374)[0]  # 약 200m
    assert ev.same_place("어니언 성수", 37.5446, 127.0557, "어니언 성수점", 37.5449, 127.0557)[0]  # 약 33m, 지점명만 다름
    assert not ev.same_place("어니언 성수", 37.5446, 127.0557, "어니언 성수점", 37.5452, 127.0557)[0]  # 약 67m


def test_lodging_repeated_every_night_is_not_duplicate():
    places = [_p(1, "a", "식당"), _p(2, "가평 펜션", "숙소"), _p(1, "b", "카페", day=2), _p(2, "가평 펜션", "숙소", day=2)]
    assert ev.evaluate(_resp(places), CENTER, 30_000)["dup_suspects"] == 0


def test_mislabel_by_name_words():
    places = [
        _p(1, "카페앤", "식당"),  # 이름은 카페
        _p(2, "서호식당", "관광지"),  # 이름은 식당
        _p(3, "청평자연휴양림", "관광지"),  # 정상
        _p(4, "성수동카페거리", "놀거리"),  # 거리는 가게가 아니다 → 의심 안 함
        _p(5, "봉녀수제비", "관광지"),
        _p(6, "메모레", "카페"),  # 이름에 단서 없음 → 의심 안 함
    ]
    m = ev.evaluate(_resp(places), CENTER, 30_000)
    assert [(x["name"], x["category"], x["looks_like"]) for x in m["mislabel_places"]] == [
        ("카페앤", "식당", "카페"), ("서호식당", "관광지", "식당"), ("봉녀수제비", "관광지", "식당"),
    ]
    assert m["mislabels"] == 3


def test_warning_texts_are_saved(tmp_path):
    r = _resp([_p(1, "a", "식당"), _p(2, "b", "카페")])
    r.meta.warnings = ["Day 1 일정이 종료 시각(20:00)을 넘어 c을(를) 뺐어요", "지도에서 확인되지 않았거나 중복된 장소 1곳을 제외했어요"]
    m = ev.evaluate(r, CENTER, 1500)
    assert m["warnings"] == 2 and m["warnings_text"] == r.meta.warnings
    path = ev.save_results(tmp_path, ["seongsu_walk"], "2026-11-26", {"seongsu_walk": m}, "표")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["date"] == "2026-11-26" and saved["results"]["seongsu_walk"]["warnings_text"] == r.meta.warnings


def test_compare_with_old_file_without_new_metrics():
    new = ev.evaluate(_resp([_p(1, "a", "식당"), _p(2, "b", "카페")]), CENTER, 1500)
    old = {k: v for k, v in new.items() if k not in ("dup_suspects", "dup_pairs", "mislabels", "mislabel_places", "warnings_text", "overtime_max_min")}
    table = ev.render_compare({"x": old}, {"x": new})
    row = next(line for line in table.splitlines() if line.startswith("| x |"))
    assert "- → 0" in row  # 옛 파일에 없는 지표는 '-' 로, 오류 없이
    assert "-" in ev.render_table({"x": old}).splitlines()[2]


# ---------- 결과 파일: 덮어쓰기 방지 · 시나리오별 합치기 ----------


def test_saving_twice_in_the_same_second_does_not_overwrite(tmp_path):
    now = datetime(2026, 11, 26, 10, 0, 0)
    a = ev.save_results(tmp_path, ["songdo_family"], "2026-11-26", {"songdo_family": {"error": "1"}}, "a", now=now)
    b = ev.save_results(tmp_path, ["songdo_family"], "2026-11-26", {"songdo_family": {"error": "2"}}, "b", now=now)
    assert a != b and a.name == "20261126-100000_songdo_family.json" and b.name == "20261126-100000_songdo_family-2.json"
    assert json.loads(a.read_text(encoding="utf-8"))["results"]["songdo_family"]["error"] == "1"
    assert b.with_suffix(".md").read_text(encoding="utf-8") == "b"
    assert ev.result_path(tmp_path, list(ev.SCENARIOS), now).name == "20261126-100000_all.json"


def test_summarize_groups_runs_by_scenario(tmp_path):
    def run(cafe: bool, dups: int):
        places = [_p(1, "a", "식당"), _p(2, "b", "카페" if cafe else "관광지")]
        return {**ev.evaluate(_resp(places), CENTER, 1500), "dup_suspects": dups}

    now = datetime(2026, 11, 26, 10, 0, 0)
    ev.save_results(tmp_path, ["songdo_family"], "2026-11-26", {"songdo_family": run(True, 0)}, "", now=now)
    ev.save_results(tmp_path, ["songdo_family"], "2026-11-26", {"songdo_family": run(False, 1)}, "", now=now)
    old = {k: v for k, v in run(True, 0).items() if k not in ("dup_suspects", "mislabels")}  # 새 지표가 없는 옛 결과
    (tmp_path / "old.json").write_text(json.dumps({"date": "2026-11-26", "results": {"songdo_family": old, "busan_walk": {"error": "x", "elapsed_s": 1}}}), encoding="utf-8")
    files = ev.expand_paths([str(tmp_path / "*.json")])
    assert len(files) == 3
    table = ev.summarize(files)
    songdo = next(line for line in table.splitlines() if line.startswith("| songdo_family |"))
    cells = [c.strip() for c in songdo.split("|")[1:-1]]
    assert cells[1] == "3" and cells[2] == "0"  # 실행 3회, 실패 0
    assert cells[5] == "1/3회" and cells[6] == "1"  # 구성 미흡 1회, 카페 0곳인 날 1
    assert cells[9] == "1"  # 중복의심은 값이 있는 2회만 더한다
    assert next(line for line in table.splitlines() if line.startswith("| busan_walk |")).split("|")[3].strip() == "1"  # 실패 1
    assert "출발일 2026-11-26" in table



# ---------- 품질 점검용 구성 지표: 볼거리 0곳인 날 · 식당 또는 카페 3곳 이상인 날 (구성 미흡 판정과 별개) ----------


def test_quality_days_from_places_and_not_in_comp_ok():
    # busan_walk 수정 후 형태: 카페 3 · 식당 2 · 볼거리 0 → 구성 미흡은 아니지만 두 지표에 잡힌다
    places = [_p(1, "블랙업커피", "카페"), _p(2, "해운대집밥", "식당"), _p(3, "모또", "카페"), _p(4, "스턴커피", "카페"), _p(5, "수림횟집", "식당")]
    m = ev.evaluate(_resp(places), CENTER, 1500)
    assert m["comp_ok"] and m["no_play_days"] == ["1"] and m["crowded_days"] == ["1"]
    row = ev.render_table({"busan": m}).splitlines()[2]
    assert "| 1 | 1 |" in row and "⚠구성 미흡" not in row


def test_quality_days_from_old_results_comp_or_titles_or_na():
    from_comp = {"comp": {"1": {"식당": 2, "카페": 2, "볼거리": 1}, "2": {"식당": 3, "카페": 2, "볼거리": 0}}}  # jeonju 수정 후 D2
    assert ev.quality_days(from_comp) == {"no_play_days": ["2"], "crowded_days": ["2"]}
    from_titles = {"titles": ["D1-1 블랙업커피[카페]", "D1-2 해운대집밥[식당]", "D1-3 모또[카페]", "D1-4 스턴커피[카페]", "D1-5 라한호텔[숙소]"]}
    assert ev.quality_days(from_titles) == {"no_play_days": ["1"], "crowded_days": ["1"]}  # 숙소는 세지 않는다
    assert ev.quality_days({"titles": ["알 수 없는 형식"]}) is None  # 추정하지 않음
    assert ev.quality_days({}) is None
    assert ev._q_count({}, "no_play_days") == "N/A"


def test_summarize_shows_quality_day_columns(tmp_path):
    now = datetime(2026, 11, 26, 10, 0, 0)
    busy = ev.evaluate(_resp([_p(1, "a", "카페"), _p(2, "b", "식당"), _p(3, "c", "카페"), _p(4, "d", "카페")]), CENTER, 1500)
    ev.save_results(tmp_path, ["busan_walk"], "2026-11-26", {"busan_walk": busy}, "", now=now)
    (tmp_path / "old.json").write_text(json.dumps({"date": "2026-11-26", "results": {"busan_walk": {"places": 3, "unverified": 0, "outside": 0, "comp_ok": True,
        "over_budget": False, "warnings": 0, "elapsed_s": 1.0, "comp": {"1": {"식당": 1, "카페": 1, "볼거리": 1}}}}}), encoding="utf-8")
    table = ev.summarize(ev.expand_paths([str(tmp_path / "*.json")]))
    head = next(line for line in table.splitlines() if line.startswith("| 시나리오"))
    assert "볼거리 0곳인 날" in head and "식당·카페 3곳+ 날" in head
    cells = [c.strip() for c in next(line for line in table.splitlines() if line.startswith("| busan_walk |")).split("|")[1:-1]]
    assert cells[11] == "1" and cells[12] == "1"  # 2회 중 한 번만 해당


# ---------- 식사 시각 점검 지표 (묶음 2 전후 비교용, 구성 미흡 판정과 별개) ----------


def _sched(start, end, places, day_start=None):
    days = sorted({p[0] for p in places})
    return {
        "day_start": {str(d): (day_start or {}).get(d, start) for d in days},
        "day_end": {str(d): end for d in days},
        "places": [{"day": d, "order": i + 1, "name": f"p{i}", "category": c, "arrive": a, "stay_min": s} for i, (d, c, a, s) in enumerate(places)],
    }


def _day(start, end, places, day="1"):
    return ev.meal_days(_sched(start, end, places))[day]


def _resp_times(places, start="11:00", end="20:00"):
    r = CourseResponse(course_id="c", request=CourseRequest(region="성수동", date="2026-11-26", start_time=start, end_time=end),
                       places=places, legs=[], answer_md="")
    r.meta.est_cost_total = 10_000
    return r


def test_meal_seongsu_reproduction():
    # 11/21 성수동: 11:00~20:00, 마지막 식당 16:07, 17:37 종료
    places = [_p(1, "성수동카페거리", "놀거리", arrive="11:00", stay_min=60), _p(2, "하노이별", "식당", arrive="12:19", stay_min=90),
              _p(3, "카페서울숲", "카페", arrive="13:53", stay_min=60), _p(4, "메모레", "카페", arrive="15:01", stay_min=60),
              _p(5, "채선당", "식당", arrive="16:07", stay_min=90)]
    m = ev.evaluate(_resp_times(places), CENTER, 1500)
    d1 = m["meal_days"]["1"]
    assert d1["no_dinner"] is True and d1["early_dinner"] is True and d1["early_end_min"] == 143
    assert m["comp_ok"] and m["schedule"]["day_start"] == {"1": "11:00"} and m["schedule"]["places"][4]["arrive"] == "16:07"
    assert ev.meal_summary([m]) == {"no_dinner": "1/1", "early_dinner": "1/1", "early_first_meal": "-", "early_end": "143 (1일)"}


def test_meal_dinner_window_and_early_dinner_are_separate():
    two_eats_1715 = _day("11:00", "20:00", [(1, "식당", "12:00", 60), (1, "카페", "14:00", 60), (1, "식당", "17:15", 60)])
    assert (two_eats_1715["no_dinner"], two_eats_1715["early_dinner"]) == (False, True)
    late = _day("11:00", "20:00", [(1, "식당", "12:00", 60), (1, "식당", "18:30", 60)])
    assert (late["no_dinner"], late["early_dinner"]) == (False, False)
    one_eat_1600 = _day("11:00", "20:00", [(1, "카페", "12:00", 60), (1, "식당", "16:00", 60)])
    assert (one_eat_1600["no_dinner"], one_eat_1600["early_dinner"]) == (True, False)  # 식당 2곳 미만이면 이른 저녁 아님


def test_meal_lunch_rule_boundaries():
    assert _day("10:30", "20:00", [(1, "식당", "10:59", 60), (1, "카페", "12:30", 60)])["early_first_meal"] is True
    at_1031 = _day("10:31", "20:00", [(1, "식당", "10:59", 60)])
    assert at_1031["lunch_rule"] is False and at_1031["early_first_meal"] is None  # 출발 > 10:30 → 미적용
    assert _day("11:00", "20:00", [(1, "식당", "11:30", 60)])["early_first_meal"] is None


def test_meal_dinner_rule_boundaries():
    at_1500 = _day("15:00", "20:00", [(1, "식당", "16:00", 60)])
    assert at_1500["lunch_rule"] is False and at_1500["dinner_rule"] is True and at_1500["no_dinner"] is True
    assert _day("15:01", "20:00", [(1, "식당", "16:00", 60)])["dinner_rule"] is False
    end_18 = _day("11:00", "18:00", [(1, "식당", "12:00", 60)])
    assert end_18["dinner_rule"] is False and end_18["no_dinner"] is None


def test_meal_early_end_is_zero_when_course_runs_over():
    assert _day("11:00", "20:00", [(1, "식당", "19:30", 60)])["early_end_min"] == 0  # 20:30 종료 → 초과는 종료초과 지표가 다룬다


def test_meal_lodging_is_ignored_for_last_place():
    md = ev.meal_days(_sched("10:00", "21:00", [(1, "식당", "12:00", 60), (1, "카페", "14:00", 60), (1, "숙소", "20:30", 60),
                                                (2, "관광지", "10:00", 60), (2, "식당", "18:00", 60)]))
    assert md["1"]["early_end_min"] == 21 * 60 - 15 * 60  # 숙소(20:30) 가 아니라 카페가 끝나는 15:00 기준
    assert md["2"]["early_end_min"] == 21 * 60 - 19 * 60


def test_meal_missing_times_are_na_and_excluded_from_average():
    md = ev.meal_days(_sched("11:00", "20:00", [(1, "식당", "", 60), (2, "식당", "12:00", 60), (2, "식당", "18:00", 60)]))
    assert md["1"]["dinner_rule"] is None and md["1"]["early_end_min"] is None
    assert md["2"]["early_end_min"] == 60
    assert ev.meal_summary([{"meal_days": md}])["early_end"] == "60 (1일)"  # 계산 가능한 날만 평균
    assert ev.meal_days(_sched("bad", "20:00", [(1, "식당", "12:00", 60)]))["1"]["dinner_rule"] is None


def test_meal_old_results_without_schedule_are_na(tmp_path):
    # 옛 결과 파일: 장소별 도착·체류가 저장돼 있지 않아 복원 불가 → N/A, 오류 없음
    old = {"places": 2, "unverified": 0, "outside": 0, "comp_ok": True, "over_budget": False, "warnings": 0, "elapsed_s": 1.0,
           "comp": {"1": {"식당": 1, "카페": 1, "볼거리": 0}}, "titles": ["D1-1 a[식당]", "D1-2 b[카페]"]}
    assert ev.meal_days_of(old) is None
    assert set(ev.meal_summary([old]).values()) == {"N/A"}
    (tmp_path / "old.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_walk": old}}), encoding="utf-8")
    row = next(line for line in ev.summarize([tmp_path / "old.json"]).splitlines() if line.startswith("| seongsu_walk |"))
    assert row.count("N/A") == 4


def test_meal_metrics_do_not_change_composition_or_failure():
    places = [_p(1, "a", "식당", arrive="11:00", stay_min=60), _p(2, "b", "카페", arrive="12:30", stay_min=60)]
    m = ev.evaluate(_resp_times(places, start="10:00", end="20:00"), CENTER, 1500)
    assert m["comp_ok"] and m["days_lacking"] == [] and m["unverified"] == 0
    assert m["meal_days"]["1"]["no_dinner"] is True  # 점검 지표에만 잡힌다

# ---------- trace 저장 (판단 근거 재구성용. 표·비교·요약 출력은 그대로) ----------


def test_trace_is_saved_as_short_steps_and_old_results_still_work(tmp_path):
    from odiro.api.schemas import TraceStep

    places = [_p(1, "a", "관광지"), _p(2, "b", "식당"), _p(3, "c", "카페")]
    r = _resp(places)
    r.meta.trace = [TraceStep(node="verify_places", status="done", ms=1200, detail="3/3 확인"),
                    TraceStep(node="optimize_route", status="done", ms=300, detail="3곳 2구간", debug="Day 1 저녁 식당: 후보 없음")]
    m = ev.evaluate(r, CENTER, 1500)
    assert m["trace"] == [{"node": "verify_places", "status": "done", "ms": 1200, "detail": "3/3 확인"},
                          {"node": "optimize_route", "status": "done", "ms": 300, "detail": "3곳 2구간", "debug": "Day 1 저녁 식당: 후보 없음"}]
    assert ev.render_table({"x": m}) == ev.render_table({"x": {k: v for k, v in m.items() if k != "trace"}})  # 표는 그대로
    # trace 가 없는 옛 결과와 섞어도 요약·비교가 된다
    old = {k: v for k, v in m.items() if k != "trace"}
    (tmp_path / "old.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_walk": old}}), encoding="utf-8")
    (tmp_path / "new.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_walk": m}}), encoding="utf-8")
    assert "| seongsu_walk |" in ev.summarize(ev.expand_paths([str(tmp_path / "*.json")]))
    assert "seongsu_walk" in ev.render_compare({"seongsu_walk": old}, {"seongsu_walk": m})
    assert ev.trace_of(_resp(places)) == []  # trace 가 빈 응답


# ---------- 묶음 3 지표: 해 진 뒤 야외 · 입장 마감 후 도착 · 늦은 점심 · 비 규칙 · 식당 직전 장거리 · 웹 건수 ----------


def _resp_day(places, legs, start="11:00", end="20:00", transport="car", sunset="17:12", rain=False, pop=0.2, web=7):
    from odiro.api.schemas import IntroOut, LegOut

    r = CourseResponse(course_id="c", request=CourseRequest(region="가평", date="2026-11-28", start_time=start, end_time=end, transport=transport),
                       places=[], legs=[], answer_md="")
    r.places = [PlaceOut(order=i + 1, day=1, name=n, category=c, lat=37.5 + i * 0.01, lng=127.0, kakao_place_id=str(i), arrive=a, stay_min=s,
                         intro=IntroOut(use_time=u) if u else None) for i, (n, c, a, s, u) in enumerate(places)]
    r.legs = [LegOut(from_idx=i, to_idx=i + 1, transport=transport, duration_min=d, distance_m=1000) for i, d in enumerate(legs)]
    r.meta.sun.sunset = sunset
    r.meta.weather.rain, r.meta.weather.pop, r.meta.web_docs = rain, pop, web
    return r


CP = "[하절기(4월~10월)] - 09:00~19:00 (입장 마감 18:00)[동절기(11월~3월)] - 09:00~18:00 (입장 마감 17:00)"


def test_time_of_day_metrics_from_response():
    places = [("설미재미술관", "관광지", "11:00", 120, ""), ("카페드모파상", "카페", "13:23", 60, ""), ("산이좋은사람들", "식당", "15:01", 90, ""),
              ("청평자연휴양림", "관광지", "17:06", 120, CP), ("남산전망대", "관광지", "19:30", 30, ""), ("숙소", "숙소", "20:10", 0, "")]
    m = ev.evaluate(_resp_day(places, [23, 38, 35, 10, 40], rain=True, pop=0.6), CENTER, 100_000)
    t = m["time_of_day"]
    assert t["dark_outdoor"] == 1  # 휴양림 (전망대는 밤에 가는 곳이라 제외)
    assert t["after_entry"] == 1 and t["entry_judged"] == 1  # 입장 마감 17:00 뒤 도착
    assert t["late_lunch_days"] == ["1"]  # 11:00 출발, 첫 식당 15:01
    assert t["rain_rule"] is True and t["pop"] == 0.6
    assert t["long_pre_meal_legs"] == 1  # 카페→식당 38분 (자차 30분 초과)
    assert t["web_docs"] == 7
    row = ev.render_table({"gapyeong": m}).splitlines()[2]
    assert "| 1 | 1/1 | 1일 | 발동(60%) | 1 | 7 |" in row  # 묶음 3 칸 (뒤에 묶음 4 칸이 이어진다)


def test_time_of_day_walk_limit_and_no_rain():
    places = [("볼", "관광지", "11:00", 60, ""), ("점심", "식당", "12:25", 60, "")]
    m = ev.evaluate(_resp_day(places, [25], transport="walk", rain=False, pop=0.4, web=0), CENTER, 100_000)
    t = m["time_of_day"]
    assert t["long_pre_meal_legs"] == 1 and t["late_lunch_days"] == [] and t["rain_rule"] is False and t["dark_outdoor"] == 0
    assert "| 0 | 0/0 | 0일 | -(40%) | 1 | 0 |" in ev.render_table({"x": m}).splitlines()[2]


def test_time_of_day_old_results_compatible(tmp_path):
    places = [("볼", "관광지", "11:00", 240, ""), ("점심", "식당", "15:21", 60, "")]
    new = ev.evaluate(_resp_day(places, [5]), CENTER, 100_000)
    old = {k: v for k, v in new.items() if k != "time_of_day"}  # 옛 결과 파일: 새 지표 없음 (일정 원자료로 늦은 점심만 계산)
    assert ev.time_metrics_of(old)["late_lunch_days"] == ["1"] and ev.time_metrics_of(old)["dark_outdoor"] is None
    assert "| - | - | 1일 | - | - | - |" in ev.render_table({"x": old}).splitlines()[2]
    (tmp_path / "a.json").write_text(json.dumps({"date": "2026-11-28", "results": {"gapyeong_preset": old}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"date": "2026-11-28", "results": {"gapyeong_preset": new}}), encoding="utf-8")
    table = ev.summarize(ev.expand_paths([str(tmp_path / "*.json")]))
    assert "해 진 뒤 야외" in table and "| gapyeong_preset |" in table
    cmp = ev.render_compare({"gapyeong_preset": old}, {"gapyeong_preset": new})
    assert "늦은 점심" in cmp.splitlines()[0] and "| gapyeong_preset |" in cmp


def test_time_summary_does_not_hide_unknown_runs(tmp_path):
    # D3-3: 묶음 3 지표가 없는 옛 실행과 새 실행을 합칠 때, 미확인을 0 으로 더한 것처럼 보이면 안 된다 (_origin_cells 와 같은 표시)
    places = [("설미재미술관", "관광지", "11:00", 120, ""), ("카페드모파상", "카페", "13:23", 60, ""), ("산이좋은사람들", "식당", "15:01", 90, ""),
              ("청평자연휴양림", "관광지", "17:06", 120, CP)]
    new = ev.evaluate(_resp_day(places, [23, 38, 35], rain=True, pop=0.6), CENTER, 100_000)
    old = {k: v for k, v in new.items() if k != "time_of_day"}
    cells = ev._time_cells([old, new])
    assert cells == ["1+미확인 1회", "1/1+미확인 1회", "2일", "1/1회+미확인 1회", "1+미확인 1회", "7.0 (미확인 1회 제외)"]
    assert ev._time_cells([new, new]) == ["2", "2/2", "2일", "2/2회", "2", "7.0"]  # 모두 알면 예전처럼 합계
    assert ev._time_cells([old, old]) == ["-", "-", "2일", "-", "-", "-"]  # 모두 모르면 '-' (늦은 점심은 일정 원자료로 계산)
    assert ev._time_cells([new])[:2] == ["1", "1/1"] and ev._time_cells([old])[0] == "-"  # 한 번 실행 표시는 그대로
    (tmp_path / "a.json").write_text(json.dumps({"date": "2026-11-28", "results": {"gapyeong_preset": old}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"date": "2026-11-28", "results": {"gapyeong_preset": new}}), encoding="utf-8")
    row = next(line for line in ev.summarize(ev.expand_paths([str(tmp_path / "*.json")])).splitlines() if line.startswith("| gapyeong_preset |"))
    assert "| 1+미확인 1회 | 1/1+미확인 1회 | 2일 |" in row


# ---------- 묶음 4 지표: 코스의 체인 수(사용자 지정 구분) · 자동 보충 술집 수 ----------


def _resp_origin(names_cats, debug):
    from odiro.api.schemas import TraceStep

    places = [_p(i + 1, n, c) for i, (n, c) in enumerate(names_cats)]
    r = _resp(places)
    if debug is not None:
        r.meta.trace = [TraceStep(node="optimize_route", status="done", detail="3곳 2구간", debug=debug)]
    return r


def test_origin_metrics_from_debug():
    debug = ("Day 1 점심 순서: 점심 규칙 아님; 장소 출처: 체인 2곳(채선당월남쌈&샤브샤브 성수점: 사용자 지정, 스타벅스 서울숲역: 자동 보충 Q5), "
             "자동 보충 술집 1곳(골목포차: 자동 보충 M4)")
    m = ev.evaluate(_resp_origin([("채선당월남쌈&샤브샤브 성수점", "식당"), ("스타벅스 서울숲역", "카페"), ("골목포차", "식당")], debug), CENTER, 1500)
    o = m["origins"]
    assert o == {"chains": 2, "chains_user": 1, "auto_bars": 1}
    assert ev.render_table({"x": m}).splitlines()[2].endswith("| 2 (사용자 1) | 1 |")


def test_origin_metrics_unknown_is_dash_not_zero(tmp_path):
    # 판단 기록이 없는 결과(옛 파일·debug 없음): 체인 수는 이름으로 셀 수 있지만 사용자 지정·자동 보충 술집은 모름 → '-'
    m = ev.evaluate(_resp_origin([("채선당월남쌈&샤브샤브 성수점", "식당"), ("성수커피", "카페")], None), CENTER, 1500)
    assert m["origins"] == {"chains": 1, "chains_user": None, "auto_bars": None}
    assert ev.render_table({"x": m}).splitlines()[2].endswith("| 1 (사용자 -) | - |")
    old = {k: v for k, v in m.items() if k != "origins"}  # 옛 결과 파일: origins 키 자체가 없음 → 저장된 일정 이름으로 체인 수만
    assert ev.origin_metrics_of(old) == {"chains": 1, "chains_user": None, "auto_bars": None}
    (tmp_path / "a.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_walk": old}}), encoding="utf-8")
    assert "| seongsu_walk |" in ev.summarize(ev.expand_paths([str(tmp_path / "*.json")]))
    cmp = ev.render_compare({"seongsu_walk": old}, {"seongsu_walk": m})
    assert "체인" in cmp.splitlines()[0] and "| seongsu_walk |" in cmp


def test_origin_summary_does_not_hide_unknown_runs(tmp_path):
    # 판단 기록이 없는 옛 실행(사용자 지정·자동술집 미확인)과 새 실행을 합칠 때, 미확인을 0 으로 더한 것처럼 보이면 안 된다
    debug = "장소 출처: 체인 1곳(채선당월남쌈&샤브샤브 성수점: 사용자 지정), 자동 보충 술집 1곳(골목포차: 자동 보충 예비)"
    new = ev.evaluate(_resp_origin([("채선당월남쌈&샤브샤브 성수점", "식당"), ("골목포차", "식당")], debug), CENTER, 1500)
    old = {k: v for k, v in ev.evaluate(_resp_origin([("채선당월남쌈&샤브샤브 성수점", "식당")], None), CENTER, 1500).items() if k != "origins"}
    assert ev._origin_cells([old, new]) == ["2 (사용자 1+미확인 1회)", "1+미확인 1회"]
    assert ev._origin_cells([new]) == ["1 (사용자 1)", "1"] and ev._origin_cells([old]) == ["1 (사용자 -)", "-"]
    (tmp_path / "a.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_must": old}}), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps({"date": "2026-11-26", "results": {"seongsu_must": new}}), encoding="utf-8")
    row = next(line for line in ev.summarize(ev.expand_paths([str(tmp_path / "*.json")])).splitlines() if line.startswith("| seongsu_must |"))
    assert row.endswith("| 2 (사용자 1+미확인 1회) | 1+미확인 1회 |")


def test_origin_system_selected_must_chain_not_counted_as_user():
    debug = "장소 출처: 체인 2곳(스타벅스 강릉강문해변점: 꼭 넣을 곳(시스템 선택), 이디야커피 강릉점: 사용자 지정), 자동 보충 술집 0곳"
    m = ev.evaluate(_resp_origin([("스타벅스 강릉강문해변점", "카페"), ("이디야커피 강릉점", "카페")], debug), CENTER, 1500)
    assert m["origins"] == {"chains": 2, "chains_user": 1, "auto_bars": 0}
