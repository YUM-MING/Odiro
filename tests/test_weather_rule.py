"""R1: 비 예보 기준 (실제 OpenWeather 호출 없음 — 3시간 예보 항목을 직접 넣는다)."""

from datetime import UTC, datetime, timedelta

from odiro.agent import nodes
from odiro.tools import get_weather


def _slots(monkeypatch, *slots):
    """slots: (KST 시, pop, main, 3시간 강수량mm) — 오늘 날짜로 만든다."""
    today = datetime.now(UTC) + timedelta(hours=9)
    items = []
    for hour, pop, main, mm in slots:
        kst = today.replace(hour=hour, minute=0, second=0, microsecond=0)
        it = {"dt": int((kst - timedelta(hours=9)).replace(tzinfo=UTC).timestamp()), "pop": pop,
              "main": {"temp": 10.0}, "weather": [{"main": main, "description": "실 비" if main == "Rain" else "구름조금"}]}
        if mm:
            it["rain"] = {"3h": mm}
        items.append(it)
    monkeypatch.setattr(get_weather, "cached", lambda *a, **k: items)
    return today.strftime("%Y-%m-%d")


def test_pop_20_light_rain_does_not_switch_to_indoor(monkeypatch):
    day = _slots(monkeypatch, (12, 0.2, "Rain", 0.2), (15, 0.1, "Clouds", 0))
    w = get_weather.weather(37.5, 127.0, day, 11, 20)
    assert w["rain"] is False and w["umbrella"] is False and w["pop"] == 0.2


def test_pop_40_umbrella_only(monkeypatch):
    day = _slots(monkeypatch, (12, 0.4, "Rain", 0.4), (15, 0.3, "Clouds", 0))
    w = get_weather.weather(37.5, 127.0, day, 11, 20)
    assert w["rain"] is False and w["umbrella"] is True


def test_pop_60_or_meaningful_amount_switches_to_indoor(monkeypatch):
    day = _slots(monkeypatch, (12, 0.6, "Rain", 0.5))
    assert get_weather.weather(37.5, 127.0, day, 11, 20)["rain"] is True
    day = _slots(monkeypatch, (12, 0.3, "Rain", 2.0))  # 확률은 낮아도 3시간 2mm 예보
    w = get_weather.weather(37.5, 127.0, day, 11, 20)
    assert w["rain"] is True and w["umbrella"] is False


def test_only_course_hours_are_used(monkeypatch):
    day = _slots(monkeypatch, (6, 0.9, "Rain", 5.0), (12, 0.1, "Clouds", 0))  # 새벽 비는 코스 시간 밖
    assert get_weather.weather(37.5, 127.0, day, 11, 20)["rain"] is False


def test_retrieve_warnings_match_new_rule(monkeypatch):
    monkeypatch.setattr(nodes.search_place, "search", lambda *a, **k: [])
    monkeypatch.setattr(nodes.rag, "search", lambda *a, **k: [])
    monkeypatch.setattr(nodes.summarize_reviews, "web_search", lambda *a, **k: [])
    monkeypatch.setattr(nodes.get_sun_times, "sun_times", lambda *a, **k: {"sunrise": "07:20", "sunset": "17:15"})
    req = {"region": "성수동", "transport": "walk", "mode": "outing", "date": "2026-11-26", "start_time": "11:00", "end_time": "20:00", "moods": []}

    def warns(wx):
        monkeypatch.setattr(nodes.get_weather, "weather", lambda *a, **k: wx)
        return nodes.retrieve({"request": req, "center": {"lat": 37.55, "lng": 127.0}, "trace": [], "warnings": []})["warnings"]

    assert warns({"available": True, "rain": False, "umbrella": False, "pop": 0.2, "summary": "실 비"}) == []
    assert warns({"available": True, "rain": False, "umbrella": True, "pop": 0.4, "summary": "실 비"}) == ["비 소식이 있어요(강수확률 40%). 우산을 챙기세요"]
    assert warns({"available": True, "rain": True, "umbrella": False, "pop": 0.6, "summary": "비"}) == ["비 예보(강수확률 60%) → 실내 위주로 구성했어요"]
