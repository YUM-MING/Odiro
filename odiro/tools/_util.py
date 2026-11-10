"""Tool 공통: 타임아웃 HTTP, diskcache, 거리 계산.

시연 안정성 전략(PLAN.md 8): 모든 외부 호출 5~8초 타임아웃, 응답은 디스크 캐시, 실패 시 폴백.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from functools import lru_cache
from typing import Any, TypeVar

import httpx
from diskcache import Cache

from odiro.config import settings

TOOL_TIMEOUT = 8.0
T = TypeVar("T")


@lru_cache(maxsize=1)
def cache() -> Cache:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    return Cache(str(settings.cache_dir / "tools"), size_limit=512 * 1024 * 1024)


def cache_key(namespace: str, *parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{namespace}:{hashlib.sha1(raw.encode()).hexdigest()}"


def cached(namespace: str, ttl: int, fn: Callable[[], T], *parts: Any) -> T:
    """parts 로 키를 만들어 캐시 조회, 없으면 fn() 실행 후 저장. 예외는 그대로 올린다 (실패는 캐시 안 함)."""
    key = cache_key(namespace, *parts)
    hit = cache().get(key)
    if hit is not None:
        return hit  # type: ignore[return-value]
    val = fn()
    cache().set(key, val, expire=ttl)
    return val


@lru_cache(maxsize=1)
def http() -> httpx.Client:
    return httpx.Client(timeout=TOOL_TIMEOUT, headers={"User-Agent": "Odiro/0.1"})


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(2 * r * math.asin(math.sqrt(a)))


def estimate_minutes(distance_m: int, transport: str) -> int:
    """직선거리 → 소요시간 추정 (폴백). 도로 우회 보정 1.3배."""
    road = distance_m * 1.3
    speed_m_per_min = {"walk": 70.0, "transit": 330.0, "car": 450.0}.get(transport, 70.0)  # 4.2 / 20 / 27 km/h
    overhead = {"walk": 0, "transit": 10, "car": 5}.get(transport, 0)  # 환승·주차
    return max(1, round(road / speed_m_per_min) + overhead)
