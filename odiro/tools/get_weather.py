"""get_weather Tool — OpenWeather 5일/3시간 예보 → 해당 날짜 낮 시간대 요약 + 강수확률.

- 예보 범위(약 5일) 밖이면 available=False, 코스는 평소대로 짠다.
- rain=True 기준: 강수확률 ≥ 0.5 또는 주요 날씨가 비/눈. → draft 단계에서 실내 가중치, 답변에 안내.
응답은 3시간 캐시.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Any

from langchain_core.tools import tool

from odiro.config import settings
from odiro.tools._util import cached, http

FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
CACHE_TTL = 3 * 3600
RAIN_POP = 0.5


def _fetch(lat: float, lng: float) -> list[dict[str, Any]]:
    if not settings.openweather_api_key:
        raise RuntimeError("OPENWEATHER_API_KEY 없음")
    r = http().get(
        FORECAST_URL,
        params={"lat": lat, "lon": lng, "appid": settings.openweather_api_key, "units": "metric", "lang": "kr"},
    )
    r.raise_for_status()
    return r.json().get("list", [])


def weather(lat: float, lng: float, date: str, start_hour: int = 10, end_hour: int = 20) -> dict[str, Any]:
    """날짜의 [start_hour, end_hour) 구간 예보 요약. 실패/범위 밖이면 available=False (예외 없음)."""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        d = _date.today()
    if d < _date.today() or d > _date.today() + timedelta(days=5):
        return {"available": False, "summary": "", "temp_c": None, "pop": None, "rain": False, "note": "예보 범위(5일) 밖"}
    try:
        items = cached("owm", CACHE_TTL, lambda: _fetch(lat, lng), round(lat, 2), round(lng, 2))
    except Exception as e:  # noqa: BLE001
        return {"available": False, "summary": "", "temp_c": None, "pop": None, "rain": False, "note": f"날씨 조회 실패: {str(e)[:60]}"}

    # OpenWeather 는 UTC 타임스탬프. KST = UTC+9
    day_items = []
    for it in items:
        t = datetime.fromtimestamp(it["dt"], tz=UTC) + timedelta(hours=9)
        if t.date() == d and start_hour <= t.hour < end_hour:
            day_items.append(it)
    if not day_items:
        return {"available": False, "summary": "", "temp_c": None, "pop": None, "rain": False, "note": "해당 시간대 예보 없음"}

    pops = [float(it.get("pop", 0)) for it in day_items]
    temps = [float(it["main"]["temp"]) for it in day_items]
    mains = [it["weather"][0]["main"] for it in day_items]
    descs = [it["weather"][0]["description"] for it in day_items]
    max_pop = max(pops)
    wet = any(m in ("Rain", "Snow", "Thunderstorm", "Drizzle") for m in mains)
    # 가장 흔한 설명을 대표로
    summary = max(set(descs), key=descs.count)
    return {
        "available": True,
        "summary": summary,
        "temp_c": round(sum(temps) / len(temps), 1),
        "temp_min": round(min(temps), 1),
        "temp_max": round(max(temps), 1),
        "pop": round(max_pop, 2),
        "rain": bool(wet or max_pop >= RAIN_POP),
        "note": "",
    }


@tool
def get_weather(lat: float, lng: float, date: str) -> str:
    """해당 좌표·날짜의 낮 시간대 날씨 요약, 기온, 강수확률(0~1), 비 여부를 돌려준다. 5일 이내만 가능.

    Args:
        lat: 위도
        lng: 경도
        date: YYYY-MM-DD
    """
    return json.dumps(weather(lat, lng, date), ensure_ascii=False)
