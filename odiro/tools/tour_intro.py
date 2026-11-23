"""TourAPI 이용 정보(휴무일·이용시간·요금·주차) 조회.

`scripts/build_intro_lookup.py` 가 만든 data/tour_intro.json 을 읽는다. 파일이 없으면 항상 None.
장소는 카카오 검색·벡터 DB 등 출처가 섞여 content_id 가 없으므로 **이름 + 좌표 근접** 으로 찾는다.
"""

from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parent.parent.parent / "data" / "tour_intro.json"
MAX_DIST_M = 300
_STRIP = re.compile(r"\([^)]*\)|[^0-9a-z가-힣]")


def _norm(name: str) -> str:
    return _STRIP.sub("", name.lower())


def _dist_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dy = (lat2 - lat1) * 111_000
    dx = (lng2 - lng1) * 111_000 * math.cos(math.radians(lat1))
    return math.hypot(dx, dy)


@lru_cache(maxsize=1)
def _table() -> dict[str, list[dict[str, Any]]]:
    if not PATH.exists():
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for r in json.loads(PATH.read_text(encoding="utf-8")):
        out.setdefault(_norm(r["n"]), []).append(r)
    return out


def _match(name: str, lat: float, lng: float) -> dict[str, Any] | None:
    """이름이 같고 300m 안에 있는 TourAPI 장소 줄 (가장 가까운 것). 없으면 None."""
    key = _norm(name)
    if not key:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for r in _table().get(key, []):
        d = _dist_m(lat, lng, r["lat"], r["lng"])
        if d <= MAX_DIST_M and (best is None or d < best[0]):
            best = (d, r)
    return best[1] if best else None


def find_intro(name: str, lat: float, lng: float) -> dict[str, str] | None:
    """이름이 같고 300m 안에 있는 TourAPI 장소의 이용 정보. 없으면 None (이미지만 있는 줄도 None)."""
    r = _match(name, lat, lng)
    vals = {k: v for k, v in (r or {}).items() if k not in ("n", "lat", "lng", "img")}
    return vals or None


# TourAPI 이미지 호스트. 수집 데이터의 89% 가 이미 이 호스트의 https 주소라 https 지원이 확인됨 → http 도 https 로 바꿔 쓴다
HTTPS_IMAGE_HOSTS = ("tong.visitkorea.or.kr",)


def https_image(url: str | None) -> str:
    """https 로 보여 줄 수 있는 이미지 주소. https 는 그대로, http 는 https 지원이 확인된 호스트만 바꾸고, 나머지는 빈 문자열."""
    if not url:
        return ""
    if url.startswith("https://"):
        return url
    if url.startswith("http://") and url[len("http://"):].split("/", 1)[0] in HTTPS_IMAGE_HOSTS:
        return "https://" + url[len("http://"):]
    return ""


def find_image(name: str, lat: float, lng: float) -> str | None:
    """이름이 같고 300m 안에 있는 TourAPI 장소의 대표 이미지(firstimage, https). 없으면 None."""
    r = _match(name, lat, lng)
    return https_image((r or {}).get("img")) or None
