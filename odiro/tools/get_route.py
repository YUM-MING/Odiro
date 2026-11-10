"""get_route Tool — 장소 간 이동시간·거리·경로.

- 자차(car)      : Kakao Mobility 길찾기 (일 1만 회)
- 뚜벅이(walk)   : Tmap 보행자 길찾기 (일 1만 회). 2.5km 초과 구간은 대중교통으로 간주해 추정값
- 폴백           : API 실패/한도 → 직선거리 × 1.3 보정으로 시간 추정 (estimated=True)
응답은 7일 캐시 (좌표를 소수 4자리로 반올림해 키 생성).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from odiro.config import settings
from odiro.tools._util import cached, estimate_minutes, haversine_m, http

MOBILITY_URL = "https://apis-navi.kakaomobility.com/v1/directions"
TMAP_PED_URL = "https://apis.openapi.sk.com/tmap/routes/pedestrian"
CACHE_TTL = 7 * 24 * 3600
WALK_MAX_M = 2500  # 이보다 멀면 뚜벅이는 대중교통
MAX_POLYLINE_POINTS = 120


def _thin(points: list[list[float]], n: int = MAX_POLYLINE_POINTS) -> list[list[float]]:
    if len(points) <= n:
        return points
    step = len(points) / n
    out = [points[int(i * step)] for i in range(n)]
    out.append(points[-1])
    return out


def _fallback(lat1: float, lng1: float, lat2: float, lng2: float, transport: str) -> dict[str, Any]:
    d = haversine_m(lat1, lng1, lat2, lng2)
    return {
        "transport": transport,
        "duration_min": estimate_minutes(d, transport),
        "distance_m": int(d * 1.3),
        "polyline": [[lat1, lng1], [lat2, lng2]],
        "estimated": True,
    }


def _kakao_car(lat1: float, lng1: float, lat2: float, lng2: float) -> dict[str, Any]:
    if not settings.kakao_mobility_api_key:
        raise RuntimeError("KAKAO_MOBILITY_API_KEY 없음")
    r = http().get(
        MOBILITY_URL,
        params={"origin": f"{lng1},{lat1}", "destination": f"{lng2},{lat2}", "priority": "RECOMMEND"},
        headers={"Authorization": f"KakaoAK {settings.kakao_mobility_api_key}"},
    )
    r.raise_for_status()
    route = r.json()["routes"][0]
    if route.get("result_code") != 0:
        raise RuntimeError(route.get("result_msg", "경로 없음"))
    summary = route["summary"]
    pts: list[list[float]] = []
    for sec in route.get("sections", []):
        for road in sec.get("roads", []):
            v = road.get("vertexes", [])
            pts.extend([[v[i + 1], v[i]] for i in range(0, len(v) - 1, 2)])  # (x,y) → [lat,lng]
    return {
        "transport": "car",
        "duration_min": max(1, round(summary["duration"] / 60)),
        "distance_m": int(summary["distance"]),
        "polyline": _thin(pts) or [[lat1, lng1], [lat2, lng2]],
        "estimated": False,
        "toll": summary.get("fare", {}).get("toll", 0),
    }


def _tmap_walk(lat1: float, lng1: float, lat2: float, lng2: float) -> dict[str, Any]:
    if not settings.tmap_app_key:
        raise RuntimeError("TMAP_APP_KEY 없음")
    r = http().post(
        TMAP_PED_URL,
        params={"version": 1},
        headers={"appKey": settings.tmap_app_key, "Content-Type": "application/json"},
        json={
            "startX": lng1, "startY": lat1, "endX": lng2, "endY": lat2,
            "startName": "start", "endName": "end",
            "reqCoordType": "WGS84GEO", "resCoordType": "WGS84GEO",
        },
    )
    r.raise_for_status()
    feats = r.json().get("features", [])
    if not feats:
        raise RuntimeError("경로 없음")
    props = feats[0]["properties"]
    pts: list[list[float]] = []
    for f in feats:
        g = f.get("geometry", {})
        if g.get("type") == "LineString":
            pts.extend([[c[1], c[0]] for c in g["coordinates"]])
    return {
        "transport": "walk",
        "duration_min": max(1, round(props["totalTime"] / 60)),
        "distance_m": int(props["totalDistance"]),
        "polyline": _thin(pts) or [[lat1, lng1], [lat2, lng2]],
        "estimated": False,
    }


def route(lat1: float, lng1: float, lat2: float, lng2: float, transport: str = "walk") -> dict[str, Any]:
    """구간 하나의 이동 정보. 실패해도 예외 없이 추정값을 돌려준다."""
    key = (round(lat1, 4), round(lng1, 4), round(lat2, 4), round(lng2, 4), transport)
    straight = haversine_m(lat1, lng1, lat2, lng2)
    if straight < 30:
        return {"transport": transport, "duration_min": 1, "distance_m": straight, "polyline": [[lat1, lng1], [lat2, lng2]], "estimated": False}
    try:
        if transport == "car":
            return cached("route_car", CACHE_TTL, lambda: _kakao_car(lat1, lng1, lat2, lng2), *key)
        if straight > WALK_MAX_M:
            # 대중교통 API 는 쓰지 않는다 (쿼터·복잡도). 추정값으로 충분히 그럴듯하게.
            fb = _fallback(lat1, lng1, lat2, lng2, "transit")
            return fb
        return cached("route_walk", CACHE_TTL, lambda: _tmap_walk(lat1, lng1, lat2, lng2), *key)
    except Exception:  # noqa: BLE001 — 폴백이 곧 전략
        return _fallback(lat1, lng1, lat2, lng2, "car" if transport == "car" else ("transit" if straight > WALK_MAX_M else "walk"))


@tool
def get_route(from_lat: float, from_lng: float, to_lat: float, to_lng: float, transport: str = "walk") -> str:
    """두 지점 사이 이동 시간(분)·거리(m)·경로 좌표를 돌려준다.

    Args:
        from_lat: 출발 위도
        from_lng: 출발 경도
        to_lat: 도착 위도
        to_lng: 도착 경도
        transport: "walk"(도보, 2.5km 초과면 대중교통 추정) 또는 "car"(자차)
    """
    return json.dumps(route(from_lat, from_lng, to_lat, to_lng, transport), ensure_ascii=False)
