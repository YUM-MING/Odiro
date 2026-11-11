"""에이전트 노드의 결정적(LLM·네트워크 없는) 부분 테스트."""

from __future__ import annotations

import pytest

from odiro.agent import nodes


def _p(name: str, cat: str = "관광지", day: int = 1, order: int = 1, lat: float = 37.5445, lng: float = 127.0560, **kw):
    return {"name": name, "category": cat, "day": day, "order": order, "lat": lat, "lng": lng,
            "kakao_place_id": name, "verified": True, "stay_min": 60, "reason": "", **kw}


# ---------- 수정 대상 해석 ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3번째를 실내로 바꿔줘", 2),
        ("세 번째 장소 좀 더 조용한 데로", 2),
        ("첫번째를 카페로", 0),
        ("마지막 장소를 실내 놀이공간으로", 4),
        ("7번째를 바꿔줘", None),  # 범위 밖
        ("2번째랑 3번째를 바꿔줘", None),  # 대상이 둘 → LLM 에 맡김
        ("좀 더 조용한 곳으로", None),
    ],
)
def test_parse_target_single_day(text, expected):
    places = [_p(f"p{i}", order=i + 1) for i in range(5)]
    assert nodes._parse_target(text, places) == expected


def test_parse_target_with_day():
    places = [_p(f"a{i}", day=1, order=i + 1) for i in range(3)] + [_p(f"b{i}", day=2, order=i + 1) for i in range(3)]
    assert nodes._parse_target("2일차 첫 번째를 바꿔줘", places) == 3
    assert nodes._parse_target("둘째 날 마지막을 카페로", places) == 5
    assert nodes._parse_target("Day 1 마지막을 숙소 근처로", places) == 2
    assert nodes._parse_target("5번째를 바꿔줘", places) == 4  # 날짜 언급이 없으면 전체 목록 순서


# ---------- 비 예보 ----------


def test_enforce_rain_swaps_outdoor_for_indoor_spares():
    cands = [
        _p("수목원", indoor=False, order=1),
        _p("식당", "식당", order=2),
        _p("호수", indoor=False, order=3),
        _p("섬", indoor=False, order=4),
    ]
    spares = [_p("박물관", indoor=True, order=0), _p("전망대", indoor=False, order=0), _p("카페", "카페", order=0)]
    out, left_spares, leftover = nodes._enforce_rain(cands, spares, max_outdoor=1)
    assert [c["name"] for c in out] == ["수목원", "식당", "호수", "박물관"]  # 뒤쪽부터 교체, 실내 예비는 하나뿐
    assert out[3]["order"] == 4
    assert leftover == 1
    assert [s["name"] for s in left_spares] == ["전망대", "카페"]


def test_enforce_rain_keeps_course_when_within_limit():
    cands = [_p("공원", indoor=False), _p("미술관", indoor=True), _p("식당", "식당", indoor=False)]
    out, _, leftover = nodes._enforce_rain(cands, [], max_outdoor=1)
    assert out == cands and leftover == 0  # 식당은 indoor 값과 무관하게 실내 취급


# ---------- 순서 ----------


def test_best_order_keeps_lodging_last():
    places = [_p("A", lat=37.50), _p("펜션", "숙소", lat=37.51), _p("B", lat=37.52), _p("C", lat=37.90)]
    ordered = nodes._best_order(places)
    assert ordered[-1]["name"] == "펜션"
    assert {p["name"] for p in ordered} == {"A", "B", "C", "펜션"}


# ---------- verify_places ----------


def _state(cands, spares=None, **kw):
    req = {"region": "성수동", "transport": "walk", "mode": "outing", "days": 1, **kw.pop("request", {})}
    return {"request": req, "center": {"lat": 37.5445, "lng": 127.0560, "label": "성수동"}, "conditions": "",
            "candidates": cands, "spares": spares or [], "trace": [], "warnings": [], "rejected": [], **kw}


@pytest.fixture
def fake_verify(monkeypatch):
    """lat 이 있는 후보만 '지도에서 확인됨' 으로 본다."""

    def _fake(c, center, radius, hint):
        return {**c, "verified": bool(c.get("lat"))}

    monkeypatch.setattr(nodes, "_verify_one", _fake)
    monkeypatch.setattr(nodes, "MAX_VERIFY_ROUNDS", 0)  # LLM 보충 끔


def test_edit_keeps_original_when_replacement_unverified(fake_verify):
    old = _p("원래카페", "카페", order=3)
    cands = [_p("A", order=1), _p("B", "식당", order=2), {"name": "없는곳", "category": "카페", "day": 1, "order": 3, "verified": False}]
    out = nodes.verify_places(_state(cands, edit_slot={"index": 2, "old": old, "planned": "없는곳"}, instruction="3번째를 실내로"))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "원래카페"]  # 5곳 → 4곳 처럼 줄어들지 않는다
    assert "그대로" in out["edit_note"]


def test_edit_uses_alternate_and_reports_actual_place(fake_verify):
    old = _p("원래카페", "카페", order=3)
    cands = [_p("A", order=1), _p("B", "식당", order=2), {"name": "없는곳", "category": "카페", "day": 1, "order": 3, "verified": False}]
    spares = [_p("대안카페", "카페", order=0)]
    out = nodes.verify_places(_state(cands, spares, edit_slot={"index": 2, "old": old, "planned": "없는곳"}, instruction="3번째를 실내로"))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "대안카페"]
    assert out["edit_note"].startswith("원래카페 → 대안카페")
    assert "없는곳" in out["edit_note"]  # 처음 고른 후보가 아니라 실제 들어간 곳을 알린다


def test_edit_rejects_replacement_already_in_course(fake_verify):
    old = _p("원래카페", "카페", order=3)
    cands = [_p("A", order=1), _p("B", "식당", order=2), _p("A", order=3)]
    out = nodes.verify_places(_state(cands, edit_slot={"index": 2, "old": old, "planned": "A"}, instruction="3번째를 바꿔줘"))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "원래카페"]


def test_walk_outlier_replaced_by_nearby_spare(fake_verify):
    cands = [_p("A", lat=37.5445), _p("B", "식당", lat=37.5450), _p("C", "카페", lat=37.5455), _p("먼공원", lat=37.5700)]  # 약 2.8km
    spares = [_p("더먼곳", lat=37.6000), _p("가까운전시", lat=37.5460)]
    out = nodes.verify_places(_state(cands, spares))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "C", "가까운전시"]
    assert "먼공원" in out["rejected"]


def test_car_mode_does_not_drop_far_places(fake_verify):
    cands = [_p("A", lat=37.5445), _p("B", "식당", lat=37.5450), _p("C", "카페", lat=37.5455), _p("먼공원", lat=37.5700)]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    assert len(out["verified"]) == 4


def test_trip_adds_lodging_to_non_final_days(fake_verify):
    cands = [_p("A", day=1), _p("B", "식당", day=1, lat=37.60), _p("C", day=2), _p("D", "식당", day=2)]
    stays = [
        {"name": "먼호텔", "lat": 37.90, "lng": 127.0560, "kakao_place_id": "h1", "address": "", "category_group": "AD5"},
        {"name": "가까운펜션", "lat": 37.61, "lng": 127.0560, "kakao_place_id": "h2", "address": "", "category_group": "AD5"},
    ]
    out = nodes.verify_places(_state(cands, stay_docs=stays, request={"transport": "car", "mode": "trip", "days": 2}))
    day1 = [p for p in out["verified"] if p["day"] == 1]
    day2 = [p for p in out["verified"] if p["day"] == 2]
    assert day1[-1]["name"] == "가까운펜션" and day1[-1]["category"] == "숙소"  # Day 1 마지막 장소에서 가까운 숙소
    assert all(p["category"] != "숙소" for p in day2)  # 마지막 날에는 숙소 없음


def test_near_center_filters_only_docs_with_coords():
    center = {"lat": 37.39, "lng": 126.64}
    docs = [
        {"doc_id": "near", "lat": 37.40, "lng": 126.65},
        {"doc_id": "far", "lat": 37.48, "lng": 126.63},  # 약 10km
        {"doc_id": "blog"},  # 좌표 없는 블로그 문서는 유지
    ]
    assert [d["doc_id"] for d in nodes._near_center(docs, center, 5000)] == ["near", "blog"]


def test_walk_course_split_in_two_clusters_is_pulled_together(fake_verify):
    # 두 무리 사이가 약 1.9km: 가장 가까운 이웃만 보면 통과하지만 동선 한가운데 기준으로는 걸러져야 한다
    cands = [_p("A", lat=37.5445), _p("B", "식당", lat=37.5450), _p("C", "카페", lat=37.5455), _p("D", lat=37.5620), _p("E", lat=37.5625)]
    spares = [_p("가까운1", lat=37.5440), _p("가까운2", lat=37.5460)]
    out = nodes.verify_places(_state(cands, spares))
    assert {p["name"] for p in out["verified"]} == {"A", "B", "C", "가까운1", "가까운2"}


def test_walk_outlier_without_replacement_is_kept_with_warning(fake_verify):
    cands = [_p("A", lat=37.5445), _p("B", "식당", lat=37.5450), _p("C", "카페", lat=37.5455), _p("먼공원", lat=37.5700)]
    out = nodes.verify_places(_state(cands))
    assert len(out["verified"]) == 4  # 대신할 곳이 없으면 장소 수를 줄이지 않는다
    assert any("먼공원" in w for w in out["warnings"])


def test_review_snippets_must_mention_the_place():
    from odiro.tools.summarize_reviews import mentions

    assert mentions("카페빵조각", "송도 빵지순례: 카페 빵조각 다녀온 후기")
    assert mentions("송도갈비 본점", "인천 송도갈비 솔직 후기")
    assert not mentions("카페빵조각", "안스베이커리 메뉴 추천: 차이나타운 신상 카페")
    assert not mentions("타입스", "성수동 부지 개발 기대감… 삼표시멘트 급등")


def test_duplicate_place_is_refilled_from_spares(fake_verify):
    cands = [_p("A"), _p("B", "식당"), _p("A", order=3)]  # 같은 장소가 두 번
    out = nodes.verify_places(_state(cands, [_p("C")], request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "C"]
