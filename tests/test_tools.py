"""Tool 순수 로직 테스트 (네트워크 없음): 이름 매칭, 거리·시간 추정, 길찾기 폴백 구조, 날씨 범위 밖."""

from odiro.agent.nodes import _best_order, _hhmm_add, _places_per_day, _same_role
from odiro.tools._util import estimate_minutes, haversine_m
from odiro.tools.get_route import _fallback
from odiro.tools.get_sun_times import sun_times
from odiro.tools.get_weather import weather
from odiro.tools.search_place import _norm_name, name_similarity


def sim(a: str, b: str) -> float:
    return name_similarity(_norm_name(a), _norm_name(b))


def test_name_similarity_accepts_variants():
    assert sim("어니언 성수", "어니언 성수점") >= 0.8
    assert sim("카페 드 파리", "카페드파리") == 1.0
    assert sim("아침고요수목원", "아침고요 수목원") == 1.0
    assert sim("서울숲", "서울숲공원") >= 0.8
    assert sim("가평 레일바이크", "가평레일파크") >= 0.5


def test_name_similarity_rejects_different_places():
    assert sim("청평호반", "청평호반닭갈비막국수 설악점") < 0.5  # 짧은 이름이 긴 상호에 포함되는 경우
    assert sim("청평호", "청평호수민박") < 0.5
    assert sim("성수 감성카페", "대림창고") < 0.3
    assert sim("존재하지않는가게XYZ", "성수동 카페거리") < 0.3


def test_haversine_and_estimate():
    d = haversine_m(37.5445, 127.0559, 37.5444, 127.0374)  # 성수역 → 서울숲 약 1.6km
    assert 1500 < d < 1750
    assert estimate_minutes(1000, "walk") >= 15
    assert estimate_minutes(10000, "car") < estimate_minutes(10000, "walk")


def test_route_fallback_shape():
    r = _fallback(37.5445, 127.0559, 37.5444, 127.0374, "walk")
    assert r["estimated"] is True and r["transport"] == "walk"
    assert r["polyline"][0] == [37.5445, 127.0559] and len(r["polyline"]) == 2
    assert r["duration_min"] > 0 and r["distance_m"] > 0


def test_sun_times_seoul_november():
    s = sun_times(37.5665, 126.978, "2026-11-15")
    assert s["sunrise"].startswith("07:") and s["sunset"].startswith("17:")


def test_weather_out_of_range_no_network():
    w = weather(37.5665, 126.978, "2030-01-01")
    assert w["available"] is False and w["rain"] is False and "범위" in w["note"]


def test_places_per_day_and_same_role():
    assert _places_per_day({"start_time": "11:00", "end_time": "20:00", "mode": "outing"}) == 5
    assert _places_per_day({"start_time": "10:00", "end_time": "21:00", "mode": "trip"}) == 5  # trip 은 최대 5
    assert _places_per_day({"start_time": "18:00", "end_time": "20:00"}) == 3  # 최소 3
    assert _same_role("관광지", "산책") and _same_role("식당", "식당") and not _same_role("식당", "카페")


def test_best_order_reorders_only_when_much_shorter():
    a = {"lat": 37.50, "lng": 127.00}
    b = {"lat": 37.60, "lng": 127.00}
    c = {"lat": 37.51, "lng": 127.00}
    # a → b → c 는 왕복, a → c → b 가 훨씬 짧다
    assert [p["lat"] for p in _best_order([a, b, c])] == [37.50, 37.51, 37.60] or [p["lat"] for p in _best_order([a, b, c])] == [37.60, 37.51, 37.50]
    # 이미 괜찮은 순서는 그대로
    assert _best_order([a, c, b]) == [a, c, b]


def test_hhmm_add():
    assert _hhmm_add("11:50", 25) == "12:15"
    assert _hhmm_add("23:30", 60) == "00:30"
