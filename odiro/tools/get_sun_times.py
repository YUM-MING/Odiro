"""get_sun_times Tool — astral 로 일출·일몰 오프라인 계산 (API 키 불필요)."""

from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime, timedelta

from astral import LocationInfo
from astral.sun import sun
from langchain_core.tools import tool

TZ = "Asia/Seoul"


def sun_times(lat: float, lng: float, date: str) -> dict[str, str]:
    d = datetime.strptime(date, "%Y-%m-%d").date() if date else _date.today()
    loc = LocationInfo("", "KR", TZ, lat, lng)
    s = sun(loc.observer, date=d, tzinfo=TZ)
    return {
        "date": d.isoformat(),
        "sunrise": s["sunrise"].strftime("%H:%M"),
        "sunset": s["sunset"].strftime("%H:%M"),
        "golden_hour_start": (s["sunset"] - timedelta(minutes=60)).strftime("%H:%M"),
        "dusk": s["dusk"].strftime("%H:%M"),
    }


@tool
def get_sun_times(lat: float, lng: float, date: str) -> str:
    """해당 좌표·날짜의 일출·일몰 시각(한국시간)을 돌려준다. 일몰 명소 방문 시각을 잡을 때 쓴다.

    Args:
        lat: 위도
        lng: 경도
        date: YYYY-MM-DD
    """
    return json.dumps(sun_times(lat, lng, date), ensure_ascii=False)
