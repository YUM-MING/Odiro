"""에이전트 노드의 결정적(LLM·네트워크 없는) 부분 테스트."""

from __future__ import annotations

import itertools

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


# ---------- 여행: 권역별 날짜 묶기 · 숙소 · 꼭 넣을 곳 ----------


def test_regroup_days_puts_nearby_places_on_the_same_day():
    # 북쪽 권역(37.90)과 남쪽 권역(37.70)이 날마다 섞여 있는 초안
    places = [
        _p("북1", day=1, order=1, lat=37.90), _p("남식당", "식당", day=1, order=2, lat=37.70), _p("남1", day=1, order=3, lat=37.71),
        _p("남2", day=2, order=1, lat=37.69), _p("북식당", "식당", day=2, order=2, lat=37.91), _p("북2", day=2, order=3, lat=37.89),
    ]
    out = nodes._regroup_days(places, 2)
    by_day = {d: {p["name"] for p in out if p["day"] == d} for d in (1, 2)}
    assert {frozenset(v) for v in by_day.values()} == {frozenset({"북1", "북2", "북식당"}), frozenset({"남1", "남2", "남식당"})}


def test_regroup_days_keeps_plan_when_already_grouped():
    places = [_p("북1", day=1, lat=37.90), _p("북2", day=1, lat=37.91), _p("남1", day=2, lat=37.70), _p("남2", day=2, lat=37.71)]
    assert nodes._regroup_days(places, 2) == places


def test_best_order_starts_from_previous_lodging():
    stay = _p("숙소", "숙소", lat=37.60)
    places = [_p("먼곳", lat=37.90), _p("중간", lat=37.75), _p("가까운곳", lat=37.61)]
    assert [p["name"] for p in nodes._best_order(places, start=stay)] == ["가까운곳", "중간", "먼곳"]


def test_user_lodging_is_used_every_night(fake_verify):
    cands = [_p("A", day=1), _p("LLM호텔", "숙소", day=1), _p("B", day=2), _p("C", day=3)]
    mine = {"name": "내숙소", "lat": 37.55, "lng": 127.05, "kakao_place_id": "mine", "address": ""}
    out = nodes.verify_places(_state(cands, user_stay=mine, request={"transport": "car", "mode": "trip", "days": 3, "lodging": "내숙소"}))
    stays = [(p["day"], p["name"]) for p in out["verified"] if p["category"] == "숙소"]
    assert stays == [(1, "내숙소"), (2, "내숙소")]  # 초안의 숙소 대신 사용자가 적은 숙소, 마지막 날은 없음


def test_must_have_place_is_inserted_when_draft_skipped_it(fake_verify):
    cands = [_p("A", order=1), _p("B", "식당", order=2), _p("C", "카페", order=3), _p("D", order=4)]
    must = [{"name": "반지공방 온", "lat": 37.5447, "lng": 127.0561, "kakao_place_id": "ring", "address": "", "keyword": "반지공방", "category_full": "문화,예술 > 공방"}]
    out = nodes.verify_places(_state(cands, must_docs=must, must_keywords=["반지공방"]))
    names = [p["name"] for p in out["verified"]]
    assert "반지공방 온" in names and len(names) == 4  # 볼거리 한 자리와 바꿔 넣는다 (식당·카페는 유지)
    assert {"B", "C"} <= set(names)


def test_must_have_not_duplicated_when_draft_already_has_it(fake_verify):
    cands = [_p("A"), _p("B", "식당"), _p("성수 반지공방", kakao_category="문화,예술 > 공방")]
    must = [{"name": "다른 반지공방", "lat": 37.5447, "lng": 127.0561, "kakao_place_id": "ring2", "address": "", "keyword": "반지공방"}]
    out = nodes.verify_places(_state(cands, must_docs=must, must_keywords=["반지공방"]))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "성수 반지공방"]


def test_budget_warning_uses_estimated_costs(fake_verify):
    cands = [_p("A", est_cost=40000), _p("B", "식당", est_cost=50000), _p("C", "카페", est_cost=20000)]
    out = nodes.verify_places(_state(cands, request={"budget": 100000}))
    assert any("예산" in w for w in out["warnings"])


def test_regroup_gives_every_day_a_restaurant():
    # 식당 3곳이 전부 남쪽에 있어도 날마다 하나씩은 돌아가게
    places = [
        _p("북1", day=1, lat=37.90), _p("북2", day=1, lat=37.91), _p("남1", day=2, lat=37.70), _p("남2", day=2, lat=37.71),
        _p("남식당1", "식당", day=1, lat=37.70), _p("남식당2", "식당", day=1, lat=37.705), _p("북1b", day=2, lat=37.905),
        _p("남1b", day=1, lat=37.715),
    ]
    out = nodes._regroup_days(places, 2)
    for d in (1, 2):
        assert any(p["category"] == "식당" for p in out if p["day"] == d)


def test_day_sequence_follows_time_of_day():
    ps = [_p("저녁식당", "식당", lat=37.56), _p("볼거리1", lat=37.50), _p("카페", "카페", lat=37.52), _p("점심식당", "식당", lat=37.505), _p("볼거리2", lat=37.54)]
    cats = [p["category"] for p in nodes._day_sequence(ps)]
    assert cats == ["관광지", "식당", "카페", "관광지", "식당"]  # 오전 볼거리 → 점심 → 카페 → 오후 볼거리 → 저녁


def test_outdoor_detected_by_name_even_if_flagged_indoor():
    assert nodes._is_outdoor(_p("송도센트럴파크", "놀거리", indoor=True))
    assert nodes._is_outdoor(_p("아침고요수목원", indoor=True))
    assert nodes._is_outdoor(_p("자라섬", "놀거리", indoor=True))
    assert not nodes._is_outdoor(_p("인천도시역사관", indoor=True))
    assert not nodes._is_outdoor(_p("서울숲 근처 식당", "식당", indoor=False))


def test_unverified_slots_are_filled_from_known_real_places(fake_verify):
    cands = [
        _p("A"), _p("B", "식당"),
        {"name": "없는카페", "category": "카페", "day": 1, "order": 3, "verified": False},
        {"name": "없는전시", "category": "관광지", "day": 1, "order": 4, "verified": False},
    ]
    pois = [{"name": "실존카페", "lat": 37.5446, "lng": 127.0561, "kakao_place_id": "c1", "category_group": "CE7", "address": ""}]
    rag = [
        {"doc_type": "place", "title": "실존박물관", "lat": 37.5448, "lng": 127.0562, "addr": "", "one_line": "실내 전시"},
        {"doc_type": "place", "title": "한강공원", "lat": 37.5447, "lng": 127.0561, "addr": ""},  # 비 예보 → 야외는 제외
    ]
    out = nodes.verify_places(_state(cands, poi_docs=pois, rag_docs=rag, weather={"rain": True}, request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "실존카페", "실존박물관"]


def test_day_with_only_cafes_and_restaurants_gets_an_attraction(fake_verify):
    cands = [_p("카페1", "카페"), _p("식당1", "식당"), _p("카페2", "카페"), _p("식당2", "식당")]
    rag = [
        {"doc_type": "place", "title": "호수공원", "lat": 37.5446, "lng": 127.0561, "addr": ""},
        {"doc_type": "place", "title": "실존미술관", "lat": 37.5450, "lng": 127.0563, "addr": "", "one_line": "실내 전시"},
    ]
    out = nodes.verify_places(_state(cands, rag_docs=rag, weather={"rain": True}, request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert names == ["카페1", "식당1", "실존미술관", "식당2"]  # 남는 카페 자리를 실내 볼거리로 (비 예보 → 공원보다 미술관)


def test_attraction_comes_from_map_search_when_no_curated_place_docs(fake_verify, monkeypatch):
    # 서울 밖은 큐레이션 장소 문서가 아직 없다 → 지도에서 찾은 볼거리로 채운다
    found = [{"doc_type": "place", "title": "가평레일파크", "lat": 37.5449, "lng": 127.0562, "addr": "", "kakao_place_id": "k1", "place_url": "", "one_line": "테마파크"}]
    monkeypatch.setattr(nodes, "_find_attractions", lambda req, hub, rain: found)
    cands = [_p("카페1", "카페"), _p("식당1", "식당"), _p("카페2", "카페")]
    out = nodes.verify_places(_state(cands, rag_docs=[{"doc_type": "blog", "title": "가평 카페 후기"}], request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["카페1", "식당1", "가평레일파크"]


# ---------- 11/12 피드백: 프랜차이즈 · 엉뚱한 추천 이유 · 꼭 넣을 곳 한 번만 ----------


def test_is_chain():
    assert nodes._is_chain("메가MGC커피 강릉시외버스터미널점")
    assert nodes._is_chain("스타벅스 남이섬점")
    assert not nodes._is_chain("카페서울숲")
    assert not nodes._is_chain("강릉커피거리 보사노바")


def test_chain_cafe_is_replaced(fake_verify):
    cands = [_p("A"), _p("B", "식당"), _p("메가MGC커피 강릉시외버스터미널점", "카페", reason="호수 전망이 좋은 카페", tags=["뷰맛집/일몰"])]
    pois = [
        {"name": "스타벅스 강릉점", "lat": 37.5446, "lng": 127.0561, "kakao_place_id": "s1", "category_group": "CE7", "address": ""},
        {"name": "동네로스터리", "lat": 37.5447, "lng": 127.0561, "kakao_place_id": "c1", "category_group": "CE7", "address": ""},
    ]
    out = nodes.verify_places(_state(cands, poi_docs=pois, request={"transport": "car", "region": "강릉"}))
    cafe = out["verified"][2]
    assert cafe["name"] == "동네로스터리"  # 프랜차이즈는 빼고, 채울 때도 프랜차이즈는 쓰지 않는다
    assert "호수" not in cafe["reason"] and cafe["tags"] == []  # 실패한 후보의 설명·태그를 물려받지 않는다


def test_chain_allowed_when_user_asks_for_it(fake_verify):
    cands = [_p("A"), _p("B", "식당"), _p("스타벅스 강릉점", "카페")]
    out = nodes.verify_places(_state(cands, request={"transport": "car", "free_text": "스타벅스 꼭 가고 싶어"}))
    assert out["verified"][2]["name"] == "스타벅스 강릉점"


def test_must_have_appears_only_once(fake_verify):
    # 라구파스타를 Day 1, Day 2 에 모두 넣은 초안 → 한 번만 남기고 다른 식당으로
    cands = [
        _p("A", day=1), _p("라구파스타 온", "식당", day=1), _p("카페1", "카페", day=1),
        _p("B", day=2), _p("파스타집 라구", "식당", day=2, kakao_category="음식점 > 양식 > 라구파스타"), _p("카페2", "카페", day=2),
    ]
    must = [{"name": "라구파스타 온", "lat": 37.5445, "lng": 127.0560, "kakao_place_id": "라구파스타 온", "keyword": "라구파스타", "category_group": "FD6"}]
    pois = [{"name": "막국수집", "lat": 37.5446, "lng": 127.0561, "kakao_place_id": "m1", "category_group": "FD6", "address": ""}]
    out = nodes.verify_places(_state(cands, must_docs=must, must_keywords=["라구파스타"], poi_docs=pois, request={"transport": "car", "mode": "outing"}))
    names = [p["name"] for p in out["verified"]]
    assert names.count("라구파스타 온") == 1 and "파스타집 라구" not in names and "막국수집" in names


def test_must_have_restaurant_replaces_a_restaurant_slot(fake_verify):
    cands = [_p("A"), _p("닭갈비집", "식당"), _p("카페1", "카페"), _p("B")]
    must = [{"name": "라구파스타 온", "lat": 37.5446, "lng": 127.0561, "kakao_place_id": "r1", "keyword": "라구파스타", "category_group": "FD6"}]
    out = nodes.verify_places(_state(cands, must_docs=must, must_keywords=["라구파스타"], request={"transport": "car"}))
    got = {p["name"]: p["category"] for p in out["verified"]}
    assert got == {"A": "관광지", "라구파스타 온": "식당", "카페1": "카페", "B": "관광지"}  # 볼거리가 아니라 식당 자리와 바꾼다


def test_too_many_restaurants_in_a_day_are_rebalanced(fake_verify, monkeypatch):
    found = [{"doc_type": "place", "title": "올림픽뮤지엄", "lat": 37.5449, "lng": 127.0562, "addr": "", "kakao_place_id": "k1", "place_url": "", "one_line": "박물관"}]
    monkeypatch.setattr(nodes, "_find_attractions", lambda req, hub, rain: found)
    # (11/23) '국수' → '돈까스': 좌표가 같은 '칼국수'·'국수' 는 같은 가게 기준(유사도 0.85 + 50m)에 걸리므로 서로 다른 식당 이름으로
    cands = [_p("카페1", "카페"), _p("박물관A"), _p("빵집", "식당"), _p("칼국수", "식당"), _p("돈까스", "식당")]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    cats = [p["category"] for p in out["verified"]]
    assert cats.count("식당") == 2 and "올림픽뮤지엄" in [p["name"] for p in out["verified"]]
    assert not any(a == b == "식당" for a, b in itertools.pairwise(cats))  # 식당이 연달아 나오지 않는다


def test_route_step_separates_back_to_back_restaurants(monkeypatch):
    monkeypatch.setattr(nodes.get_route, "route", lambda *a, **k: {"transport": "car", "duration_min": 5, "distance_m": 1000, "polyline": [], "estimated": False})
    places = [_p("파스타", "식당", lat=37.50), _p("생선찜", "식당", lat=37.501), _p("아트센터", lat=37.502), _p("카페", "카페", lat=37.503), _p("호텔", "숙소", lat=37.504)]
    out = nodes.optimize_route({"request": {"transport": "car", "start_time": "11:00", "end_time": "20:00"}, "verified": places, "trace": [], "warnings": []})
    cats = [p["category"] for p in out["places"]]
    assert cats == ["관광지", "식당", "카페", "식당", "숙소"]


def _fake_route(monkeypatch):
    monkeypatch.setattr(nodes.get_route, "route", lambda *a, **k: {"transport": "car", "duration_min": 5, "distance_m": 1000, "polyline": [], "estimated": False})


def test_day_starts_override_start_time_per_day(monkeypatch):
    _fake_route(monkeypatch)
    places = [_p("A", day=1, lat=37.50), _p("B", "카페", day=1, lat=37.501), _p("C", day=2, lat=37.50), _p("D", "카페", day=2, lat=37.501)]
    req = {"transport": "car", "start_time": "11:00", "end_time": "20:00", "day_starts": {1: "09:00"}}
    out = nodes.optimize_route({"request": req, "verified": places, "trace": [], "warnings": []})
    first = {p["day"]: p["arrive"] for p in out["places"] if p["order"] == 1}
    assert first == {1: "09:00", 2: "11:00"}  # 지정하지 않은 날은 기존 시작 시각


def test_route_drops_last_places_when_past_end_time(monkeypatch):
    _fake_route(monkeypatch)
    places = [_p("A", lat=37.50), _p("B", "카페", lat=37.501), _p("C", lat=37.502), _p("D", "식당", lat=37.503), _p("호텔", "숙소", lat=37.504)]
    req = {"transport": "car", "start_time": "11:00", "end_time": "15:00"}
    out = nodes.optimize_route({"request": req, "verified": places, "trace": [], "warnings": []})
    body = [p for p in out["places"] if p["category"] != "숙소"]
    assert 2 <= len(body) < 4
    assert out["places"][-1]["category"] == "숙소"
    last = body[-1]
    assert nodes._hhmm_to_min(last["arrive"]) + last["stay_min"] <= nodes._hhmm_to_min("15:00")  # 숙소 체류는 계산에서 제외
    assert len(out["legs"]) == len(out["places"]) - 1
    assert any("뺐어요" in w for w in out["warnings"])


def test_route_lodging_stay_not_counted_and_no_midnight_wrap(monkeypatch):
    _fake_route(monkeypatch)
    places = [_p("A", lat=37.50), _p("B", "카페", lat=37.501), _p("호텔", "숙소", lat=37.502)]
    req = {"transport": "car", "start_time": "21:00", "end_time": "23:59"}
    out = nodes.optimize_route({"request": req, "verified": places, "trace": [], "warnings": []})
    assert len(out["places"]) == 3 and not out["warnings"]  # 숙소 60분을 더해도 경고가 없어야 한다
    late = _p("A", lat=37.50, stay_min=180), _p("B", "카페", lat=37.501, stay_min=180)
    out = nodes.optimize_route({"request": {**req, "start_time": "21:00", "end_time": "22:00"}, "verified": list(late), "trace": [], "warnings": []})
    assert any("종료 시각" in w for w in out["warnings"])  # 24시를 넘겨도 경고가 나온다


def test_modify_time_only_edit_updates_request_and_skips_swap(monkeypatch):
    plan = nodes.EditPlan(target_number=0, schedule_only=True, time_changes=[nodes.TimeChange(day=1, start_time="09:00")])

    class FakeChat:
        def with_structured_output(self, _):
            return self

        def invoke(self, _):
            return plan

    monkeypatch.setattr(nodes, "chat", lambda *_: FakeChat())
    places = [_p("A", verified=True), _p("B", "카페", order=2, verified=True)]
    out = nodes.modify({"request": {"days": 1, "mode": "outing"}, "conditions": "", "places": places, "instruction": "첫째날 9시에 시작하게 바꿔줘", "trace": []})
    assert out["time_only"] and out["request"]["day_starts"] == {1: "09:00"}
    assert [p["name"] for p in out["verified"]] == ["A", "B"]  # 장소는 그대로


def _fake_chat(monkeypatch, result):
    class FakeChat:
        def with_structured_output(self, _):
            return self

        def invoke(self, _):
            return result

    monkeypatch.setattr(nodes, "chat", lambda *_: FakeChat())


def test_extract_moods_keeps_only_tags_whose_phrase_is_in_the_text(monkeypatch):
    _fake_chat(monkeypatch, nodes.MoodTags(moods=[nodes.MoodHit(phrase="조용한", tag="감성/조용한"), nodes.MoodHit(phrase="카공", tag="감성/조용한"), nodes.MoodHit(phrase="레트로", tag="레트로"), nodes.MoodHit(phrase="핫플", tag="힙한/트렌디")]))
    assert nodes._extract_moods("조용한 카공 카페") == ["감성/조용한"]  # 레트로·핫플은 문장에 근거 표현이 없어 버린다


def test_extract_moods_returns_empty_on_llm_failure(monkeypatch):
    class Boom:
        def with_structured_output(self, _):
            raise RuntimeError("down")

    monkeypatch.setattr(nodes, "chat", lambda *_: Boom())
    assert nodes._extract_moods("조용한 카페") == []
    assert nodes._extract_moods("") == []


def test_modify_searches_rag_with_moods_from_instruction(monkeypatch):
    calls = []
    monkeypatch.setattr(nodes.rag, "search", lambda q, **kw: calls.append(kw) or [])
    monkeypatch.setattr(nodes, "_extract_moods", lambda text: ["감성/조용한"])
    _fake_chat(monkeypatch, nodes.EditPlan(target_number=0, place=None))
    places = [_p("A", verified=True), _p("B", "카페", order=2, verified=True)]
    nodes.modify({"request": {"region": "성수동", "days": 1, "mode": "outing"}, "conditions": "", "places": places, "instruction": "조용한 카페로 바꿔줘", "trace": []})
    assert calls and all(c["moods"] == ["감성/조용한"] for c in calls)


def _poi(name, group="CE7"):
    return {"name": name, "category_group": group, "lat": 37.5, "lng": 127.0}


def _blog(title, tags=(), one_line=""):
    return {"doc_id": title, "doc_type": "blog", "title": title, "snippet": "", "tags": list(tags), "one_line": one_line}


def test_rank_pois_lifts_blog_backed_cafes_and_keeps_distance_order_otherwise():
    pois = [_poi("가까운카페집"), _poi("천상가옥 성수점"), _poi("먼카페집"), _poi("단일서울")]
    docs = [_blog("성수동 카페 천상가옥 후기", ["감성/조용한"], "조용하고 아늑한 한옥 카페"), _blog("단일서울 다녀왔어요", [], "넓은 카페")]
    out = nodes._rank_pois_by_blogs(pois, docs, ["감성/조용한"])
    assert [p["name"] for p in out] == ["천상가옥 성수점", "단일서울", "가까운카페집", "먼카페집"]  # 태그까지 맞는 곳 > 언급만 > 근거 없음(거리순)
    assert out[0]["blog_mentions"] == 1 and out[0]["blog_hint"] == "조용하고 아늑한 한옥 카페"
    assert "blog_mentions" not in out[2]


def test_rank_pois_sorts_within_group_only_and_ignores_generic_names():
    pois = [_poi("가까운식당", "FD6"), _poi("송도맛집", "FD6"), _poi("카페", "CE7"), _poi("어니언", "CE7")]
    docs = [_blog("송도맛집 추천 카페 어니언 후기")]
    out = nodes._rank_pois_by_blogs(pois, docs, [])
    assert [p["name"] for p in out] == ["가까운식당", "송도맛집", "어니언", "카페"]  # 식당 그룹이 먼저, 일반 명사형 상호('송도맛집','카페')는 근거로 안 친다


def test_fmt_pois_shows_blog_hint():
    text = nodes._fmt_pois([{"name": "천상가옥", "category_full": "음식점 > 카페", "address": "성수", "blog_mentions": 2, "blog_hint": "아늑한 한옥"}, _poi("그냥카페")])
    assert "★블로그 언급 2건: 아늑한 한옥" in text and text.count("★") == 1


def _blog_cafe_setup(monkeypatch, items, hits_by_name):
    _fake_chat(monkeypatch, nodes.BlogCafes(items=items))
    monkeypatch.setattr(nodes.search_place, "search", lambda q, *a, **k: hits_by_name.get(q.split(" ", 1)[1], []))
    center = {"lat": 37.5446, "lng": 127.0557}
    docs = [_blog("성수동 카페 천상가옥 후기", ["감성/조용한"], "아늑한 한옥 카페"), _blog("성수 카페 프랙티커피 추천", ["감성/조용한"], "조용한 로스터리"), _blog("무관한 글 서브젝티브", ["힙한/트렌디"])]
    return center, [{**d, "doc_id": d["title"]} for d in docs]


def _cafe(name, dist_deg, pid):
    return {"name": name, "category_group": "CE7", "lat": 37.5446 + dist_deg, "lng": 127.0557, "kakao_place_id": pid}


def test_blog_backed_cafes_walk_keeps_only_within_800m(monkeypatch):
    items = [nodes.BlogCafe(name="천상가옥", doc=0), nodes.BlogCafe(name="프랙티커피", doc=1)]
    hits = {"천상가옥": [_cafe("천상가옥", 0.0108, "1")], "프랙티커피": [_cafe("프랙티커피", 0.0050, "2")]}  # 0.0108° ≈ 1.2km, 0.0050° ≈ 556m
    center, docs = _blog_cafe_setup(monkeypatch, items, hits)
    out = nodes._blog_backed_cafes({"region": "성수동", "transport": "walk"}, center, docs, ["감성/조용한"], 1500, set())
    assert [p["name"] for p in out] == ["프랙티커피"] and out[0]["blog_hint"] == "조용한 로스터리"
    car = nodes._blog_backed_cafes({"region": "성수동", "transport": "car"}, center, docs, ["감성/조용한"], 8000, set())
    assert [p["name"] for p in car] == ["프랙티커피", "천상가옥"]  # 자차는 800m 제한 없이 가까운 순


def test_blog_backed_cafes_drops_invented_names_and_non_cafes_and_taken(monkeypatch):
    items = [nodes.BlogCafe(name="없는카페", doc=0), nodes.BlogCafe(name="천상가옥", doc=0), nodes.BlogCafe(name="프랙티커피", doc=1)]
    hits = {"없는카페": [_cafe("없는카페", 0.001, "9")], "천상가옥": [{**_cafe("천상가옥", 0.001, "1"), "category_group": "FD6"}], "프랙티커피": [_cafe("프랙티커피", 0.001, "2")]}
    center, docs = _blog_cafe_setup(monkeypatch, items, hits)
    assert nodes._blog_backed_cafes({"region": "성수동", "transport": "walk"}, center, docs, ["감성/조용한"], 1500, {"2"}) == []  # 제목에 없는 상호·식당·이미 있는 곳은 모두 제외


# ---------- 묶음 1 (11/23): 장소 종류·중복·카페 ----------

CENTER = {"lat": 37.70, "lng": 127.40, "label": "경기 가평군"}


def _hit(name, group, full, lat=37.7001, lng=127.4001, pid="k1"):
    return {"name": name, "category_group": group, "category_full": full, "category": {"FD6": "식당", "CE7": "카페", "AT4": "관광지"}.get(group, ""),
            "lat": lat, "lng": lng, "address": "", "kakao_place_id": pid, "place_url": "", "phone": ""}


def _verify_with(monkeypatch, cand_name, cand_cat, hit):
    monkeypatch.setattr(nodes.search_place, "verify", lambda *a, **k: hit)
    return nodes._verify_one({"name": cand_name, "category": cand_cat, "day": 1, "order": 1, "verified": False}, CENTER, 30000, "가평")


# Q1. 카테고리를 카카오 업종과 맞춘다 (FD6 → 식당, CE7 → 카페, 제과·베이커리·디저트 → 카페. 그 외는 LLM 값)


def test_q1_kakao_cafe_labeled_play_becomes_cafe(monkeypatch):
    out = _verify_with(monkeypatch, "키즈카페 놀자", "놀거리", _hit("키즈카페 놀자", "CE7", "음식점 > 카페 > 테마카페 > 키즈카페"))
    assert out["verified"] and out["category"] == "카페"


def test_q1_exact_name_restaurant_labeled_attraction_becomes_restaurant(monkeypatch):
    # 이름이 완전히 같으면 업종 불일치 거절을 건너뛰는 경로 (봉녀수제비가 '관광지'로 남던 경로)
    out = _verify_with(monkeypatch, "봉녀수제비", "관광지", _hit("봉녀수제비", "FD6", "음식점 > 한식 > 국수"))
    assert out["verified"] and out["category"] == "식당"


def test_q1_bakery_is_a_cafe(monkeypatch):
    # 기준선 gapyeong_preset: "자잠157 베이커리카페" 가 '식당'으로 표시됨
    out = _verify_with(monkeypatch, "자잠157 베이커리카페", "식당", _hit("자잠157 베이커리카페", "FD6", "음식점 > 간식 > 제과,베이커리"))
    assert out["category"] == "카페"


def test_q1_attraction_and_unknown_group_keep_llm_category(monkeypatch):
    assert _verify_with(monkeypatch, "설미재미술관", "관광지", _hit("설미재미술관", "AT4", "여행 > 관광,명소"))["category"] == "관광지"
    assert _verify_with(monkeypatch, "가평레일바이크", "놀거리", _hit("가평레일바이크", "", "스포츠,레저 > 레일바이크"))["category"] == "놀거리"


def test_q1_lodging_is_not_overridden(monkeypatch):
    # 여행 숙소는 날짜 구성의 기준이라 건드리지 않는다
    out = _verify_with(monkeypatch, "가평 펜션카페", "숙소", _hit("가평 펜션카페", "CE7", "음식점 > 카페"))
    assert out["category"] == "숙소"


# Q2. TourAPI 음식점·숙박 문서는 볼거리 빈 자리에 쓰지 않는다 (content_type 은 한글 명칭으로 저장됨)


def _doc(title, ctype, lat=37.5447, lng=127.0561, **kw):
    return {"doc_type": "place", "title": title, "content_type": ctype, "lat": lat, "lng": lng, "addr": "", **kw}


def test_q2_restaurant_doc_not_added_as_attraction_on_day_without_one(fake_verify, monkeypatch):
    # 실험 C-2: 볼거리 없는 날 play_added 가 TourAPI 음식점 '서호식당'을 '관광지'로 넣던 문제 → 지도 볼거리로 대체
    found = [{"doc_type": "place", "title": "설미재미술관", "lat": 37.5449, "lng": 127.0562, "addr": "", "kakao_place_id": "k9", "place_url": "", "one_line": "미술관"}]
    monkeypatch.setattr(nodes, "_find_attractions", lambda req, hub, rain: found)
    cands = [_p("카페1", "카페"), _p("식당1", "식당"), _p("카페2", "카페")]
    out = nodes.verify_places(_state(cands, rag_docs=[_doc("서호식당", "음식점")], request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert "서호식당" not in names and "설미재미술관" in names


def test_q2_unverified_attraction_slot_skips_restaurant_and_lodging_docs(fake_verify):
    cands = [_p("A"), _p("B", "식당"), _p("C", "카페"), {"name": "없는전시", "category": "관광지", "day": 1, "order": 4, "verified": False}]
    rag = [_doc("봉녀수제비", "음식점"), _doc("가평 호텔", "숙박", lat=37.54471), _doc("가평레일파크", "레포츠", lat=37.5450)]
    out = nodes.verify_places(_state(cands, rag_docs=rag, request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["A", "B", "C", "가평레일파크"]


def test_q2_normal_attraction_types_are_still_used(fake_verify):
    for ctype in ("관광지", "문화시설", "레포츠", "행사", "여행코스", "쇼핑"):
        cands = [_p("A"), _p("B", "식당"), _p("C", "카페"), {"name": "없는곳", "category": "관광지", "day": 1, "order": 4, "verified": False}]
        out = nodes.verify_places(_state(cands, rag_docs=[_doc(f"정상{ctype}", ctype)], request={"transport": "car"}))
        assert out["verified"][-1]["name"] == f"정상{ctype}", ctype


def test_q2_rebalancing_restaurants_skips_restaurant_docs(fake_verify):
    # 식당 3곳 → 한 곳을 볼거리로 바꿀 때도 음식점 문서는 쓰지 않는다
    cands = [_p("카페1", "카페"), _p("박물관A"), _p("빵집", "식당", lat=37.5450), _p("칼국수", "식당", lat=37.5455), _p("돈까스", "식당", lat=37.5460)]
    rag = [_doc("갈비집", "음식점", lat=37.5451, lng=127.0560), _doc("올림픽뮤지엄", "문화시설", lat=37.5457, lng=127.0560)]  # 음식점 문서가 그날 중심에 더 가깝다
    out = nodes.verify_places(_state(cands, rag_docs=rag, request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert "갈비집" not in names and "올림픽뮤지엄" in names


# Q3. 같은 가게 판정 (정규화 이름 일치+150m 또는 유사도≥0.85+50m. 좌표만으로는 판정하지 않음. 숙소끼리는 제외)

TOUR = (37.7013794825, 127.3963235444)  # TourAPI 좌표의 '카페 드 모파상'
KAKAO = (37.70124550237815, 127.3961320593873)  # 카카오 좌표의 '카페드모파상' (약 22m)


def test_q3_fill_skips_candidate_that_is_the_same_shop(fake_verify):
    # 실험 C-1: 확인 실패한 볼거리 자리를 큐레이션 문서로 채울 때, 이미 코스에 있는 가게(띄어쓰기만 다름)는 건너뛴다
    cands = [{"name": "없는관광지", "category": "관광지", "day": 1, "order": 1, "verified": False},
             _p("카페드모파상", "카페", order=2, lat=KAKAO[0], lng=KAKAO[1], kakao_place_id="g1"), _p("서호식당", "식당", order=3, lat=37.7020, lng=127.3970)]
    rag = [_doc("카페 드 모파상", "관광지", lat=TOUR[0], lng=TOUR[1]), _doc("설미재미술관", "문화시설", lat=37.7030, lng=127.3990)]
    out = nodes.verify_places(_state(cands, rag_docs=rag, request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert names == ["설미재미술관", "카페드모파상", "서호식당"]


def test_q3_duplicate_keeps_kakao_info_in_the_earlier_slot(fake_verify):
    cands = [_p("카페 드 모파상", "관광지", order=1, lat=TOUR[0], lng=TOUR[1], kakao_place_id="", stay_min=90),
             _p("서호식당", "식당", order=2, lat=37.7020, lng=127.3970), _p("카페드모파상", "카페", order=3, lat=KAKAO[0], lng=KAKAO[1], kakao_place_id="g1")]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    kept = [p for p in out["verified"] if "모파상" in p["name"]]
    assert len(kept) == 1
    k = kept[0]
    assert (k["name"], k["kakao_place_id"], k["category"], k["lat"]) == ("카페드모파상", "g1", "카페", KAKAO[0])  # 장소 정보는 카카오 쪽
    assert (k["order"], k["stay_min"]) == (1, 90)  # 자리·체류는 먼저 배정된 쪽
    assert any("중복" in w for w in out["warnings"])  # 채울 후보가 없으면 기존 경고


def test_q3_must_have_mark_is_inherited_by_the_kept_place(fake_verify):
    # 꼭 넣을 곳(북카페)에 해당하던 쪽이 지워져도 남는 쪽이 이어받는다 → 꼭 넣을 곳을 또 끼워 넣지 않는다
    cands = [_p("책방 숲", "카페", order=1, lat=TOUR[0], lng=TOUR[1], kakao_place_id="", kakao_category="음식점 > 카페 > 북카페"),
             _p("서호식당", "식당", order=2, lat=37.7020, lng=127.3970), _p("책방숲", "카페", order=3, lat=KAKAO[0], lng=KAKAO[1], kakao_place_id="b1"),
             _p("설미재미술관", order=4, lat=37.7030, lng=127.3990)]
    must = [{"name": "다른북카페", "lat": 37.7040, "lng": 127.3995, "kakao_place_id": "m9", "keyword": "북카페", "category_group": "CE7"}]
    out = nodes.verify_places(_state(cands, must_docs=must, must_keywords=["북카페"], request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert names.count("책방숲") == 1 and "책방 숲" not in names and "다른북카페" not in names
    assert next(p for p in out["verified"] if p["name"] == "책방숲").get("must") is True


def test_q3_different_shops_30m_apart_are_both_kept(fake_verify):
    cands = [_p("로우키커피", "카페", order=1), _p("하노이별", "식당", order=2, lat=37.54477), _p("서울숲", order=3, lat=37.5450)]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["로우키커피", "하노이별", "서울숲"]


def test_q3_same_shop_on_different_days_is_kept_once(fake_verify):
    cands = [_p("카페 드 모파상", "관광지", day=1, order=1, lat=TOUR[0], lng=TOUR[1], kakao_place_id=""),
             _p("카페드모파상", "카페", day=2, order=1, lat=KAKAO[0], lng=KAKAO[1], kakao_place_id="g1")]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    assert [(p["name"], p["day"]) for p in out["verified"]] == [("카페드모파상", 1)]


def test_q3_lodging_pairs_and_rule_thresholds():
    stay = {"name": "가평 펜션", "category": "숙소", "lat": 37.70, "lng": 127.40, "kakao_place_id": "s1"}
    assert not nodes._same_shop(stay, {**stay, "day": 2})  # 여행의 같은 숙소 반복은 의도
    a = {"name": "카페 드 모파상", "category": "관광지", "lat": TOUR[0], "lng": TOUR[1], "kakao_place_id": ""}
    assert nodes._same_shop(a, {"name": "카페드모파상", "category": "카페", "lat": KAKAO[0], "lng": KAKAO[1], "kakao_place_id": "g1"})
    assert not nodes._same_shop(a, {"name": "다른가게", "category": "카페", "lat": TOUR[0], "lng": TOUR[1], "kakao_place_id": "x"})  # 좌표만 같음
    from odiro.tools import search_place
    assert (search_place.SAME_NAME_RADIUS_M, search_place.SIMILAR_NAME_MIN, search_place.SIMILAR_NAME_RADIUS_M) == (150, 0.85, 50)


# Q4. 식당·카페 빈 자리는 같은 역할 예비 후보로만 채운다 (없으면 카카오 주변 식당·카페 후보가 채운다)


def test_q4_cafe_slot_is_not_filled_with_a_different_role_spare(fake_verify):
    # 실험 B-1: 초안의 카페(프랜차이즈)가 빠지고 예비 후보는 놀거리뿐 → 예전에는 놀거리로 채워져 카페 0곳
    cands = [_p("국립인천해양박물관", order=1), _p("송도맛집A", "식당", order=2, lat=37.5446),
             _p("스타벅스 송도점", "카페", order=3, lat=37.5447), _p("송도맛집B", "식당", order=4, lat=37.5448)]
    spares = [_p("트리플스트리트", "놀거리", order=0, lat=37.5449)]
    pois = [{"name": "로컬카페", "lat": 37.5450, "lng": 127.0561, "kakao_place_id": "c1", "category_group": "CE7", "address": ""}]
    out = nodes.verify_places(_state(cands, spares, poi_docs=pois, request={"transport": "car", "region": "인천 송도"}))
    got = {p["name"]: p["category"] for p in out["verified"]}
    assert got.get("로컬카페") == "카페" and "트리플스트리트" not in got


def test_q4_attraction_slot_still_accepts_any_role_spare(fake_verify):
    # 그날 볼거리(D)가 따로 있어 '볼거리 없는 날' 보충(지도 검색)은 돌지 않는다
    cands = [{"name": "없는전시", "category": "관광지", "day": 1, "order": 1, "verified": False}, _p("B", "식당", order=2), _p("C", "카페", order=3), _p("D", "놀거리", order=4)]
    out = nodes.verify_places(_state(cands, [_p("예비카페", "카페", order=0, lat=37.5446)], request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["예비카페", "B", "C", "D"]  # 볼거리 자리는 지금처럼 다른 역할도 받는다


# Q5. 장소 3곳 이상인 날에 카페(식당)가 0곳이면 이미 받아 둔 카카오 주변 후보로 한 자리를 바꾼다 (새 검색·LLM 없음)

CAFE_POI = {"name": "로컬카페", "lat": 37.5450, "lng": 127.0561, "kakao_place_id": "c1", "category_group": "CE7", "address": "", "category_full": "음식점 > 카페"}
FOOD_POI = {"name": "동네밥집", "lat": 37.5451, "lng": 127.0561, "kakao_place_id": "f1", "category_group": "FD6", "address": "", "category_full": "음식점 > 한식"}


def _cats(out, day=1):
    return [p["category"] for p in out["verified"] if p["day"] == day]


def test_q5_day_without_cafe_gets_one_by_replacing_an_extra_attraction(fake_verify):
    # 실험 B-3: 초안에 카페가 없는 날 (볼거리 2·식당 2) → 볼거리 하나를 주변 카페로
    cands = [_p("박물관", order=1), _p("맛집A", "식당", order=2, lat=37.5446), _p("트리플스트리트", "놀거리", order=3, lat=37.5447), _p("맛집B", "식당", order=4, lat=37.5448)]
    out = nodes.verify_places(_state(cands, poi_docs=[CAFE_POI], request={"transport": "car", "end_time": "18:00"}))
    names = [p["name"] for p in out["verified"]]
    assert "로컬카페" in names and _cats(out).count("카페") == 1 and _cats(out).count("식당") == 2
    assert names == ["박물관", "맛집A", "로컬카페", "맛집B"]  # 뒤쪽 볼거리 자리에 (순서 자리 유지)


def test_q5_must_have_and_lodging_are_never_replaced(fake_verify):
    cands = [_p("반지공방 아뜰리에", "놀거리", order=1), _p("맛집A", "식당", order=2, lat=37.5446), _p("카페없는숙소", "숙소", order=3, lat=37.5447),
             _p("맛집B", "식당", order=4, lat=37.5448), _p("전시관", order=5, lat=37.5449)]
    must = [{"name": "반지공방 아뜰리에", "lat": 37.5445, "lng": 127.0560, "kakao_place_id": "반지공방 아뜰리에", "keyword": "반지공방", "category_group": ""}]
    out = nodes.verify_places(_state(cands, poi_docs=[CAFE_POI], must_docs=must, must_keywords=["반지공방"], request={"transport": "car", "end_time": "18:00"}))
    names = [p["name"] for p in out["verified"]]
    assert "반지공방 아뜰리에" in names and "카페없는숙소" in names and "로컬카페" in names and "전시관" not in names


def test_q5_no_candidate_leaves_course_and_warns(fake_verify):
    cands = [_p("박물관", order=1), _p("맛집A", "식당", order=2, lat=37.5446), _p("트리플스트리트", "놀거리", order=3, lat=37.5447)]
    out = nodes.verify_places(_state(cands, request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]] == ["박물관", "맛집A", "트리플스트리트"]
    assert any("카페" in w for w in out["warnings"])


def test_q5_second_restaurant_kept_when_day_ends_after_18(fake_verify):
    # 볼거리 1·식당 2·카페 0: 종료 20:00 이면 저녁 식당을 지키고 경고만, 18:00 이면 식당 하나를 카페로
    cands = [_p("박물관", order=1), _p("맛집A", "식당", order=2, lat=37.5446), _p("맛집B", "식당", order=3, lat=37.5448)]
    late = nodes.verify_places(_state(list(cands), poi_docs=[CAFE_POI], request={"transport": "car", "end_time": "20:00"}))
    assert [p["name"] for p in late["verified"]] == ["박물관", "맛집A", "맛집B"] and any("카페" in w for w in late["warnings"])
    early = nodes.verify_places(_state(list(cands), poi_docs=[CAFE_POI], request={"transport": "car", "end_time": "18:00"}))
    assert _cats(early).count("카페") == 1 and _cats(early).count("식당") == 1


def test_q5_day_without_restaurant_keeps_at_least_one_cafe(fake_verify):
    cands = [_p("카페1", "카페", order=1), _p("박물관", order=2, lat=37.5446), _p("카페2", "카페", order=3, lat=37.5447)]
    out = nodes.verify_places(_state(cands, poi_docs=[FOOD_POI], request={"transport": "car"}))
    assert _cats(out).count("식당") == 1 and _cats(out).count("카페") == 1 and "동네밥집" in [p["name"] for p in out["verified"]]


def test_q5_applies_to_each_day_of_a_trip(fake_verify):
    cands = [_p("A1", day=1, order=1), _p("A2", "놀거리", day=1, order=2, lat=37.5446), _p("A식당", "식당", day=1, order=3, lat=37.5447),
             _p("B1", day=2, order=1, lat=37.5448), _p("B2", "놀거리", day=2, order=2, lat=37.5449), _p("B식당", "식당", day=2, order=3, lat=37.5450)]
    pois = [CAFE_POI, {**CAFE_POI, "name": "숲속로스터리", "kakao_place_id": "c2", "lat": 37.5452}]  # 이름이 비슷하면 같은 가게로 본다
    stays = [{"name": "가평펜션", "lat": 37.5446, "lng": 127.0562, "kakao_place_id": "h1", "address": ""}]
    out = nodes.verify_places(_state(cands, poi_docs=pois, stay_docs=stays, request={"transport": "car", "mode": "trip", "days": 2}))
    assert _cats(out, 1).count("카페") == 1 and _cats(out, 2).count("카페") == 1


# Q2 보완 (11/23 평가 busan_walk·jeonju_vegan): 가까운 큐레이션 볼거리가 없으면(멀거나 음식점뿐) 지도 볼거리 검색으로 넘어간다


def test_q2_walk_day_without_near_curated_attraction_uses_map_search(fake_verify, monkeypatch):
    # busan_walk 형: 볼거리 없는 날, 큐레이션 문서는 가까운 음식점(제외됨)과 6km 밖 관광지뿐 → 예전엔 지도 검색을 안 해 볼거리 0
    found = [{"doc_type": "place", "title": "해운대해수욕장", "lat": 37.5447, "lng": 127.0562, "addr": "", "kakao_place_id": "a1", "place_url": "", "one_line": "해수욕장"}]
    monkeypatch.setattr(nodes, "_find_attractions", lambda req, hub, rain: found)
    cands = [_p("카페1", "카페", order=1), _p("식당1", "식당", order=2, lat=37.5446), _p("카페2", "카페", order=3, lat=37.5447),
             _p("카페3", "카페", order=4, lat=37.5448), _p("식당2", "식당", order=5, lat=37.5449)]
    rag = [_doc("해운대암소갈비집", "음식점", lat=37.5450), _doc("해동용궁사", "관광지", lat=37.60)]
    out = nodes.verify_places(_state(cands, rag_docs=rag, request={"transport": "walk"}))
    names = [p["name"] for p in out["verified"]]
    assert "해운대해수욕장" in names and "해운대암소갈비집" not in names and "해동용궁사" not in names


def test_q2_rebalancing_restaurants_falls_back_to_map_search_when_curated_is_far(fake_verify, monkeypatch):
    # jeonju_vegan D2 형: 식당 3곳 → 하나를 볼거리로 바꿀 때, 가까운 큐레이션 볼거리가 없으면 지도 검색 결과로
    found = [{"doc_type": "place", "title": "경기전", "lat": 37.5447, "lng": 127.0562, "addr": "", "kakao_place_id": "a2", "place_url": "", "one_line": "사적"},
             {"doc_type": "place", "title": "전동성당", "lat": 37.5448, "lng": 127.0562, "addr": "", "kakao_place_id": "a3", "place_url": "", "one_line": "성당"}]
    monkeypatch.setattr(nodes, "_find_attractions", lambda req, hub, rain: found)
    cands = [_p("식당1", "식당", order=1), _p("카페1", "카페", order=2, lat=37.5446), _p("식당2", "식당", order=3, lat=37.5447),
             _p("카페2", "카페", order=4, lat=37.5448), _p("식당3", "식당", order=5, lat=37.5449)]
    rag = [_doc("베테랑칼국수", "음식점", lat=37.5446), _doc("덕진공원", "관광지", lat=37.60)]
    out = nodes.verify_places(_state(cands, rag_docs=rag, request={"transport": "walk"}))
    cats = [p["category"] for p in out["verified"]]
    assert cats.count("식당") <= 2 and sum(c not in ("식당", "카페") for c in cats) >= 1
    assert "베테랑칼국수" not in [p["name"] for p in out["verified"]]


# 빵집은 카페 (결정 2): 카카오 주변 후보로 식당·카페 자리를 채우는 경로도 _kakao_food_role 로 역할을 정한다

BAKERY = {"name": "PNB풍년제과 한옥마을점", "lat": 37.5446, "lng": 127.0561, "kakao_place_id": "p1", "category_group": "FD6", "address": "",
          "category_full": "음식점 > 간식 > 제과,베이커리"}
RESTAURANT = {"name": "동네밥집", "lat": 37.5452, "lng": 127.0563, "kakao_place_id": "f2", "category_group": "FD6", "address": "", "category_full": "음식점 > 한식"}
ROASTERY = {"name": "로컬로스터리", "lat": 37.5452, "lng": 127.0563, "kakao_place_id": "c2", "category_group": "CE7", "address": "", "category_full": "음식점 > 카페"}


def _empty(cat, order):
    return {"name": f"없는{cat}", "category": cat, "day": 1, "order": order, "verified": False}


def test_bakery_is_not_used_for_a_restaurant_slot(fake_verify):
    cands = [_p("A", order=1), _p("카페1", "카페", order=2), _empty("식당", 3)]
    out = nodes.verify_places(_state(cands, poi_docs=[BAKERY, RESTAURANT], request={"transport": "car"}))
    assert [(p["name"], p["category"]) for p in out["verified"]][-1] == ("동네밥집", "식당")  # 제과점이 더 가까워도 식당 자리에는 안 들어감


def test_bakery_can_fill_a_cafe_slot(fake_verify):
    cands = [_p("A", order=1), _p("식당1", "식당", order=2), _empty("카페", 3)]
    out = nodes.verify_places(_state(cands, poi_docs=[BAKERY], request={"transport": "car"}))
    assert [(p["name"], p["category"]) for p in out["verified"]][-1] == ("PNB풍년제과 한옥마을점", "카페")


def test_bakery_chain_is_excluded_from_cafe_slot(fake_verify):
    chain = {**BAKERY, "name": "파리바게뜨 송도점", "kakao_place_id": "pb", "lat": 37.5445}
    cands = [_p("A", order=1), _p("식당1", "식당", order=2), _empty("카페", 3)]
    out = nodes.verify_places(_state(cands, poi_docs=[chain, ROASTERY], request={"transport": "car"}))
    names = [p["name"] for p in out["verified"]]
    assert "파리바게뜨 송도점" not in names and names[-1] == "로컬로스터리"


def test_regular_restaurant_and_cafe_keep_their_roles_in_fill(fake_verify):
    cands = [_p("A", order=1), _empty("식당", 2), _empty("카페", 3)]
    out = nodes.verify_places(_state(cands, poi_docs=[RESTAURANT, ROASTERY], request={"transport": "car"}))
    assert [(p["name"], p["category"]) for p in out["verified"]] == [("A", "관광지"), ("동네밥집", "식당"), ("로컬로스터리", "카페")]


def test_poi_without_kakao_category_keeps_old_behavior(fake_verify):
    # 업종 상세(category_full)가 없으면 그룹대로(FD6 → 식당 자리), 그룹도 없으면 식당·카페 자리에 쓰지 않는다 (기존과 같음)
    no_full = {k: v for k, v in RESTAURANT.items() if k != "category_full"}
    no_group = {**ROASTERY, "name": "그룹없는곳", "kakao_place_id": "g0", "category_group": "", "lat": 37.5446}
    cands = [_p("A", order=1), _p("카페1", "카페", order=2), _empty("식당", 3)]
    out = nodes.verify_places(_state(cands, poi_docs=[no_group, no_full], request={"transport": "car"}))
    assert [p["name"] for p in out["verified"]][-1] == "동네밥집"


def test_q5_bakery_counts_as_cafe_candidate_not_restaurant(fake_verify):
    # 카페 없는 날 → 제과점을 카페로 넣는다 / 식당 없는 날 → 제과점만 있으면 넣지 않고 경고
    no_cafe = [_p("박물관", order=1), _p("맛집A", "식당", order=2, lat=37.5447), _p("공원", "놀거리", order=3, lat=37.5448)]
    out = nodes.verify_places(_state(no_cafe, poi_docs=[BAKERY], request={"transport": "car"}))
    assert ("PNB풍년제과 한옥마을점", "카페") in [(p["name"], p["category"]) for p in out["verified"]]
    no_food = [_p("박물관", order=1), _p("카페1", "카페", order=2, lat=37.5447), _p("카페2", "카페", order=3, lat=37.5448)]
    out = nodes.verify_places(_state(no_food, poi_docs=[BAKERY], request={"transport": "car"}))
    assert "PNB풍년제과 한옥마을점" not in [p["name"] for p in out["verified"]] and any("식당" in w for w in out["warnings"])


def test_edit_fallback_does_not_offer_bakery_for_a_restaurant(monkeypatch):
    plan = nodes.EditPlan(target_number=2, place=nodes.DraftPlace(name="없는식당", category="식당", reason=""), keywords=[])
    _fake_chat(monkeypatch, plan)
    monkeypatch.setattr(nodes.search_place, "search", lambda *a, **k: [BAKERY, RESTAURANT])
    places = [_p("A", verified=True), _p("B", "식당", order=2, verified=True), _p("C", "카페", order=3, verified=True)]
    out = nodes.modify({"request": {"region": "전주", "days": 1, "mode": "outing", "transport": "car"}, "conditions": "", "places": places,
                        "instruction": "2번째를 다른 식당으로", "trace": []})
    names = [s["name"] for s in out["spares"]]
    assert "동네밥집" in names and "PNB풍년제과 한옥마을점" not in names


# 지도 볼거리 검색(_find_attractions): 업종 그룹 코드가 비어 있는 카카오 관광명소도 볼거리로 (전주 한옥마을 재현)


def _kakao_hit(name, group, full, lat=37.5447, lng=127.0562, pid=None):
    return {"name": name, "category_group": group, "category_full": full, "lat": lat, "lng": lng, "address": "", "kakao_place_id": pid or name, "place_url": ""}


def _attractions_from(monkeypatch, hits, transport="walk"):
    monkeypatch.setattr(nodes.search_place, "search", lambda *a, **k: hits)
    return [d["title"] for d in nodes._find_attractions({"region": "전주 한옥마을", "transport": transport}, (37.5445, 127.0560), False)]


def test_attraction_search_keeps_heritage_and_peak_without_group_code(monkeypatch):
    hits = [_kakao_hit("전주사고", "", "여행 > 관광,명소 > 문화유적 > 유적지"), _kakao_hit("오목대", "", "여행 > 관광,명소 > 산봉우리")]
    assert _attractions_from(monkeypatch, hits) == ["전주사고", "오목대"]


def test_attraction_search_drops_tourist_information_center_even_with_at4(monkeypatch):
    hits = [_kakao_hit("전주종합관광안내소", "", "여행 > 관광,명소 > 관광안내소"), _kakao_hit("가평관광안내소", "AT4", "여행 > 관광,명소 > 관광안내소"),
            _kakao_hit("경기전", "", "여행 > 관광,명소 > 문화유적 > 궁,궐")]
    assert _attractions_from(monkeypatch, hits) == ["경기전"]


def test_attraction_search_still_accepts_at4_and_ct1(monkeypatch):
    hits = [_kakao_hit("전주한옥마을 선비골목길", "AT4", "여행 > 관광,명소 > 테마거리"), _kakao_hit("국립전주박물관", "CT1", "문화,예술 > 문화시설 > 박물관")]
    assert _attractions_from(monkeypatch, hits) == ["전주한옥마을 선비골목길", "국립전주박물관"]


def test_attraction_search_rejects_restaurants_and_cafes_even_with_travel_category(monkeypatch):
    hits = [_kakao_hit("한옥마을 맛집", "FD6", "여행 > 관광,명소 > 맛집거리"), _kakao_hit("전망카페", "CE7", "여행 > 관광,명소 > 전망대"),
            _kakao_hit("한옥숙소", "AD5", "여행 > 관광,명소")]
    assert _attractions_from(monkeypatch, hits) == []


def test_attraction_search_rejects_results_without_group_and_category(monkeypatch):
    hits = [_kakao_hit("알수없는곳", "", ""), {**_kakao_hit("필드없음", "", ""), "category_group": None, "category_full": None}]
    assert _attractions_from(monkeypatch, hits) == []


def test_heritage_from_map_search_respects_distance_and_used_places(fake_verify, monkeypatch):
    # 지도 검색 결과가 늘어나도 기존 규칙은 그대로: 이미 쓴 장소(같은 가게 포함)와 도보 거리 밖은 빠지고 그다음 후보가 들어간다
    hits = [_kakao_hit("전주한옥마을 선비골목길", "AT4", "여행 > 관광,명소 > 테마거리"),  # Day 1 에 이미 있음
            _kakao_hit("먼 산성", "", "여행 > 관광,명소 > 문화유적 > 성", lat=37.60),  # 약 6km (도보 밖)
            _kakao_hit("전주사고", "", "여행 > 관광,명소 > 문화유적 > 유적지", lat=37.5449)]
    monkeypatch.setattr(nodes.search_place, "search", lambda *a, **k: hits)
    cands = [_p("전주한옥마을 선비골목길", day=1, order=1), _p("식당A", "식당", day=1, order=2), _p("카페A", "카페", day=1, order=3),
             _p("식당B", "식당", day=2, order=1), _p("카페B", "카페", day=2, order=2, lat=37.5446), _p("카페C", "카페", day=2, order=3, lat=37.5447)]
    out = nodes.verify_places(_state(cands, request={"transport": "walk"}))
    day2 = [p["name"] for p in out["verified"] if p["day"] == 2]
    assert "전주사고" in day2 and "먼 산성" not in day2
    assert [p["name"] for p in out["verified"]].count("전주한옥마을 선비골목길") == 1


def test_attraction_search_drops_casino_even_with_at4(monkeypatch):
    hits = [_kakao_hit("세븐럭카지노", "", "여행 > 관광,명소 > 카지노"), _kakao_hit("강원랜드카지노", "AT4", "여행 > 관광,명소 > 카지노"),
            _kakao_hit("오목대", "", "여행 > 관광,명소 > 산봉우리")]
    assert _attractions_from(monkeypatch, hits) == ["오목대"]


# ---------- 묶음 2: 식사 시각 (M1 식사 순서 틀 · M3 11시 전 첫 식당 · M2 이른 저녁 · M4 저녁 식당 덧붙이기) ----------


def _route_by_distance(monkeypatch):
    """길찾기 대신 직선거리 추정 (네트워크 없음). 실제 구간 계산 흐름(fetch_legs)은 그대로 탄다."""
    from odiro.tools._util import estimate_minutes, haversine_m

    def fake(lat1, lng1, lat2, lng2, transport="walk"):
        d = haversine_m(lat1, lng1, lat2, lng2)
        return {"transport": transport, "duration_min": estimate_minutes(d, transport), "distance_m": int(d * 1.3), "polyline": [], "estimated": False}

    monkeypatch.setattr(nodes.get_route, "route", fake)


def _opt(places, start="11:00", end="20:00", transport="walk", **state):
    req = {"transport": transport, "start_time": start, "end_time": end, "region": "성수동", "mode": "outing"}
    return nodes.optimize_route({"request": {**req, **state.pop("request", {})}, "verified": places, "trace": [], "warnings": [], **state})


def _w(name, cat, lat, lng, stay=60, **kw):
    return {"name": name, "category": cat, "lat": lat, "lng": lng, "stay_min": stay, "day": kw.pop("day", 1), "order": 1, "verified": True,
            "kakao_place_id": name, **kw}


def test_m1_two_restaurants_not_adjacent_get_meal_order(monkeypatch):
    # 북촌형: 식당 → 카페 → 식당 → 관광지 → 카페 (식당이 연달아 있지 않아 예전엔 틀을 안 탔다) → 둘째 식당이 마지막 자리로
    _route_by_distance(monkeypatch)
    bk = [_w("A식당", "식당", 37.5826, 126.9837, 70), _w("B카페", "카페", 37.5830, 126.9840), _w("C식당", "식당", 37.5835, 126.9845, 70),
          _w("북촌", "관광지", 37.5820, 126.9850, 90), _w("D카페", "카페", 37.5815, 126.9830)]
    out = _opt(bk)
    assert [p["category"] for p in out["places"]] == ["관광지", "식당", "카페", "카페", "식당"]


def test_m1_meal_order_skipped_when_route_gets_much_longer(monkeypatch):
    # 볼거리 둘이 양 끝(각 약 1.3km)에 있으면 틀(볼거리→식당→카페→볼거리→식당)이 직선거리 합을 +47%·+1.3km 늘린다 → 적용하지 않는다
    _route_by_distance(monkeypatch)
    lay = [_w("서쪽볼거리", "관광지", 37.55, 126.985), _w("식당1", "식당", 37.55, 127.000), _w("카페", "카페", 37.55, 127.001),
           _w("식당2", "식당", 37.55, 127.002), _w("동쪽볼거리", "관광지", 37.55, 127.017)]
    out = _opt(lay)
    assert [p["name"] for p in out["places"]] == ["서쪽볼거리", "식당1", "카페", "식당2", "동쪽볼거리"]
    assert "식사 순서" in out["trace"][-1]["detail"]  # 적용하지 못한 이유를 남긴다


def test_m1_keeps_fixed_order_and_edit_flow(monkeypatch):
    _route_by_distance(monkeypatch)
    bk = [_w("A식당", "식당", 37.5826, 126.9837), _w("B카페", "카페", 37.5830, 126.9840), _w("C식당", "식당", 37.5835, 126.9845), _w("북촌", "관광지", 37.5820, 126.9850)]
    fixed = _opt([{**p, "fixed_order": True} for p in bk])
    assert [p["name"] for p in fixed["places"]] == ["A식당", "B카페", "C식당", "북촌"]  # 이미 정한 순서는 존중
    edit = _opt([dict(p) for p in bk], instruction="2번째를 바꿔줘")
    assert [p["name"] for p in edit["places"]] == ["A식당", "B카페", "C식당", "북촌"]  # 수정 흐름에서는 사용자가 본 순서를 유지

def _m3_day():
    # 식당 → 관광지 → 카페 가 한 줄로 놓여 거리로는 순서가 바뀌지 않는다 (식당 1곳이라 M1 도 해당 없음)
    return [_w("아침식당", "식당", 37.55, 127.000), _w("서울숲", "관광지", 37.55, 127.001, 90), _w("숲카페", "카페", 37.55, 127.002)]


def test_m3_early_start_moves_a_sight_before_first_restaurant(monkeypatch):
    # 09:00 출발에 첫 장소가 식당이면 09:00 점심이 된다 → 뒤의 볼거리 하나를 앞으로 (식당끼리 순서는 그대로)
    _route_by_distance(monkeypatch)
    out = _opt(_m3_day(), start="09:00", end="18:00")
    assert [p["name"] for p in out["places"]] == ["서울숲", "아침식당", "숲카페"]
    assert len(out["legs"]) == 2 and out["places"][1]["arrive"] >= "10:30"
    # 그날만 이른 출발(day_starts)이어도 같은 규칙
    out = _opt(_m3_day(), start="11:00", end="18:00", request={"day_starts": {1: "09:00"}})
    assert out["places"][0]["name"] == "서울숲"


def test_m3_late_start_and_edit_flow_unchanged(monkeypatch):
    _route_by_distance(monkeypatch)
    out = _opt(_m3_day(), start="11:00", end="18:00")  # 11:00 출발: 점심 규칙 대상 아님
    assert [p["name"] for p in out["places"]] == ["아침식당", "서울숲", "숲카페"]
    out = _opt(_m3_day(), start="09:00", end="18:00", instruction="시작 시각을 9시로")  # 수정 흐름은 순서를 다시 짜지 않는다
    assert [p["name"] for p in out["places"]] == ["아침식당", "서울숲", "숲카페"]


def _seongsu_day(dinner_stay=60):
    # 성수동 재현: 13:00 출발 관광지 → 식당 → 카페 → 식당, 둘째 식당이 16시쯤 도착 (모두 100m 안팎)
    return [_w("서울숲", "관광지", 37.5444, 127.0374), _w("점심식당", "식당", 37.5446, 127.0384),
            _w("성수카페", "카페", 37.5448, 127.0394), _w("저녁식당", "식당", 37.5450, 127.0404, dinner_stay)]


def test_m2_early_dinner_pushed_to_1730_with_stretch_and_free_time(monkeypatch):
    _route_by_distance(monkeypatch)
    base = _opt(_seongsu_day(), start="13:00", end="18:00")  # 18:00 종료: 저녁 규칙 대상 아님 → 그대로
    assert base["places"][-1]["arrive"] < "16:30" and not any("자유 시간" in w for w in base["warnings"])
    out = _opt(_seongsu_day(), start="13:00", end="20:00")
    ps = out["places"]
    assert [p["name"] for p in ps] == ["서울숲", "점심식당", "성수카페", "저녁식당"]
    assert ps[-1]["arrive"] >= "17:30"
    assert ps[2]["stay_min"] == 90 and ps[0]["stay_min"] == 60  # 저녁 바로 앞 카페만 +30 (점심 앞 볼거리는 그대로)
    assert ps[1]["arrive"] == base["places"][1]["arrive"]  # 점심 시각은 안 바뀐다
    end = nodes._hhmm_to_min(ps[-1]["arrive"]) + ps[-1]["stay_min"]
    assert end <= nodes._hhmm_to_min("20:00")
    assert any(w.startswith("저녁 식사 전 자유 시간") and "분이 있어요" in w for w in out["warnings"])
    assert len(out["legs"]) == 3


def test_m2_not_applied_when_end_time_exceeded_or_one_restaurant(monkeypatch):
    _route_by_distance(monkeypatch)
    out = _opt(_seongsu_day(dinner_stay=120), start="13:00", end="19:00")  # 17:30 + 120분 = 19:30 > 19:00 → 미적용
    assert out["places"][-1]["arrive"] < "16:30" and out["places"][2]["stay_min"] == 60
    assert not any("일정이 종료 시각" in w for w in out["warnings"])
    one = [p for p in _seongsu_day() if p["name"] != "점심식당"]  # 식당 1곳인 날은 M2 대상 아님 (늦은 점심일 수 있다)
    out = _opt(one, start="13:00", end="20:00")
    assert out["places"][-1]["name"] == "저녁식당" and out["places"][-1]["arrive"] < "16:00"
    assert all(p["stay_min"] == 60 for p in out["places"]) and not any("자유 시간" in w for w in out["warnings"])


def test_m2_applies_in_edit_flow(monkeypatch):
    _route_by_distance(monkeypatch)
    out = _opt(_seongsu_day(), start="13:00", end="20:00", instruction="3번째를 바꿔줘")
    assert out["places"][-1]["arrive"] >= "17:30"


def _food_poi(name, lat, lng, group="FD6", full="음식점 > 한식"):
    return {"name": name, "lat": lat, "lng": lng, "category_group": group, "category_full": full, "kakao_place_id": f"k-{name}",
            "address": "서울 종로구", "place_url": "", "phone": ""}


def _ikseon_day(**kw):
    # 익선동형: 11:00 카페 → 점심 식당 → 관광지 → 카페, 15시쯤 끝 (식당 1곳)
    return [_w("한옥카페", "카페", 37.5740, 126.9890, **kw), _w("점심국밥", "식당", 37.5742, 126.9895, **kw),
            _w("익선동골목", "관광지", 37.5745, 126.9900, **kw), _w("레트로카페", "카페", 37.5747, 126.9905, **kw)]


_IKSEON_POIS = [_food_poi("멀리고깃집", 37.5900, 126.9700), _food_poi("동네백반", 37.5749, 126.9908), _food_poi("익선베이커리", 37.5748, 126.9906, full="음식점 > 간식 > 제과,베이커리"),
                _food_poi("김밥천국 종로점", 37.5747, 126.9906), _food_poi("골목파스타", 37.5752, 126.9912)]


def test_m4_adds_dinner_restaurant_from_poi_docs(monkeypatch):
    _route_by_distance(monkeypatch)
    out = _opt(_ikseon_day(), start="11:00", end="19:00", poi_docs=_IKSEON_POIS)
    ps = out["places"]
    assert [p["name"] for p in ps][:4] == ["한옥카페", "점심국밥", "익선동골목", "레트로카페"]
    new = ps[-1]
    # 가장 가까운 식당. 제과점(카페 역할)·프랜차이즈·동선 밖(1.1km+)은 후보가 아니다
    assert new["name"] == "동네백반" and new["category"] == "식당"
    assert new["arrive"] >= "17:30" and nodes._hhmm_to_min(new["arrive"]) + new["stay_min"] <= nodes._hhmm_to_min("19:00")
    assert new["est_cost"] == 0 and new["stay_min"] == 60 and new["reason"] == "성수동 동선에서 가까운 식당"
    assert new["kakao_place_id"] == "k-동네백반" and new["verified"] is True
    assert len(out["legs"]) == len(ps) - 1 and out["legs"][-1]["to_idx"] == len(ps) - 1
    assert any(w.startswith("저녁 식사 전 자유 시간") for w in out["warnings"])


def test_m4_not_added_when_not_a_dinner_day_or_two_restaurants_or_editing(monkeypatch):
    _route_by_distance(monkeypatch)
    out = _opt(_ikseon_day(), start="11:00", end="18:00", poi_docs=_IKSEON_POIS)  # 18:00 종료: 저녁 규칙 대상 아님
    assert len(out["places"]) == 4
    two = _ikseon_day()
    two[0] = _w("한옥만두", "식당", 37.5740, 126.9890)
    out = _opt(two, start="11:00", end="19:00", poi_docs=_IKSEON_POIS)  # 식당 2곳인 날
    assert len(out["places"]) == 4
    out = _opt(_ikseon_day(), start="11:00", end="19:00", poi_docs=_IKSEON_POIS, instruction="2번째를 바꿔줘")  # 수정 흐름
    assert len(out["places"]) == 4


def test_m4_warns_when_no_candidate(monkeypatch):
    _route_by_distance(monkeypatch)
    pois = [p for p in _IKSEON_POIS if p["name"] in ("멀리고깃집", "익선베이커리", "김밥천국 종로점")]
    pois.append(_food_poi("점심국밥", 37.5742, 126.9895) | {"kakao_place_id": "점심국밥"})  # 이미 코스에 있는 가게
    out = _opt(_ikseon_day(), start="11:00", end="19:00", poi_docs=pois)
    assert len(out["places"]) == 4
    assert "저녁 식당 후보를 찾지 못했어요" in out["warnings"]


def test_m4_not_added_when_it_would_pass_end_time(monkeypatch):
    _route_by_distance(monkeypatch)
    late = _ikseon_day()
    late[-1] = {**late[-1], "stay_min": 260}  # 레트로카페가 18:20쯤 끝 → 저녁 60분이 19:00 안에 안 들어간다
    out = _opt(late, start="11:00", end="19:00", poi_docs=_IKSEON_POIS)
    assert len(out["places"]) == 4 and "저녁 식당 후보를 찾지 못했어요" not in out["warnings"]
    # 직선 어림으로는 들어가지만 실제 길찾기 구간이 길어 넘치면 덧붙이지 않는다 (종료 시각 초과로 기존 장소를 빼지도 않는다)
    from odiro.tools._util import estimate_minutes, haversine_m

    def slow(lat1, lng1, lat2, lng2, transport="walk"):
        d = haversine_m(lat1, lng1, lat2, lng2)
        dur = 200 if (lat2, lng2) == (37.5749, 126.9908) else estimate_minutes(d, transport)
        return {"transport": transport, "duration_min": dur, "distance_m": d, "polyline": [], "estimated": False}

    monkeypatch.setattr(nodes.get_route, "route", slow)
    early = _ikseon_day()
    early[-1] = {**early[-1], "stay_min": 150}  # 16:30쯤 끝: 어림으로는 17:30 도착 가능, 실제 구간 200분이면 19:50 도착
    out = _opt(early, start="11:00", end="19:00", poi_docs=_IKSEON_POIS)
    assert [p["name"] for p in out["places"]] == ["한옥카페", "점심국밥", "익선동골목", "레트로카페"]
    assert not any("일정이 종료 시각" in w for w in out["warnings"]) and len(out["legs"]) == 3


def test_m4_keeps_lodging_last_and_must_places_on_trip_days(monkeypatch):
    _route_by_distance(monkeypatch)
    d1 = _ikseon_day(day=1) + [_w("한옥스테이", "숙소", 37.5760, 126.9920, 0, day=1)]
    d2 = [_w(n, c, lat, lng, day=2) for n, c, lat, lng in (("창덕궁", "관광지", 37.5794, 126.9910), ("궁카페", "카페", 37.5796, 126.9915),
                                                       ("궁앞식당", "식당", 37.5798, 126.9920), ("원서동길", "관광지", 37.5800, 126.9925))]
    d1[2]["must"] = True
    pois = [_food_poi("동네백반", 37.5749, 126.9908), _food_poi("원서동한식", 37.5801, 126.9927)]
    out = _opt(d1 + d2, start="11:00", end="19:00", poi_docs=pois, request={"mode": "trip"})
    day1 = [p for p in out["places"] if p["day"] == 1]
    day2 = [p for p in out["places"] if p["day"] == 2]
    assert [p["name"] for p in day1] == ["한옥카페", "점심국밥", "익선동골목", "레트로카페", "동네백반", "한옥스테이"]
    assert day1[-1]["category"] == "숙소" and any(p.get("must") for p in day1)
    i_new = next(i for i, p in enumerate(out["places"]) if p["name"] == "동네백반")
    assert any(leg["from_idx"] == i_new and leg["to_idx"] == i_new + 1 for leg in out["legs"])  # 새 식당 → 숙소 구간도 계산
    assert day2[-1]["name"] == "원서동한식" and day2[-1]["arrive"] >= "17:30"  # 날마다 따로 판단, 다른 가게
    assert len(out["legs"]) == len(out["places"]) - 2  # 구간은 날마다 따로
    assert any(w.startswith("Day 1 저녁 식사 전 자유 시간") for w in out["warnings"])
