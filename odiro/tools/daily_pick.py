"""오늘의 숨은 여행지: data/tour_intro.json 의 후보(pick) 중 날짜마다 한 곳.

후보는 scripts/build_intro_lookup.py 가 고른다 (관광 수요가 이미 몰리는 수도권·부산·제주를 뺀 시도의 자연·인문 관광지).
외부 API 호출 없음. 풀은 처음 요청 때 한 번 만들어 메모리에 둔다.

순서 만들기 — "자주 안 가는 지역"을 고르게:
  장소 수대로 그냥 섞으면 관광지가 많은 도시(경주·강릉 등)가 추천을 거의 다 차지한다.
  그래서 시군구별로 묶고, 고정 시드로 시군구 순서와 시군구 안 장소 순서를 섞은 뒤, 시군구를 돌아가며 하나씩 뽑는다(라운드 로빈).
  첫 바퀴(시군구 수만큼의 날)에는 군 단위 지역도 큰 도시와 똑같이 한 번씩 나온다. 장소가 적은 시군구가 다 나오면 남은 곳끼리 돈다.
날짜 → 장소: 인덱스 = 기준일(PICK_EPOCH)로부터 지난 일수, 선택 = 순서[인덱스 % 길이].
  같은 날짜는 항상 같은 장소, 한 바퀴(후보 수만큼의 날) 동안 같은 장소가 다시 나오지 않는다.
  ※ 후보 풀이 바뀌면(수집·배포) 순서도 바뀐다.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from odiro.tools import tour_intro

SEED = "odiro-daily-pick-v1"
PICK_EPOCH = date(2026, 11, 1)
# 한국은 서머타임이 없어 +9 고정 (Windows 에 tzdata 가 없어도 동작)
KST = timezone(timedelta(hours=9), "Asia/Seoul")
SOURCE = "한국관광공사"


def today_kst(now: datetime | None = None) -> date:
    """서버(Cloud Run)는 UTC 라 그냥 date.today() 를 쓰면 KST 00~09시에 하루 늦다."""
    return (now or datetime.now(UTC)).astimezone(KST).date()


def candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("pick") and r.get("cid") and r.get("img")]


def build_order(rows: list[dict[str, Any]], seed: str = SEED) -> list[dict[str, Any]]:
    """시군구 라운드 로빈 순서 (모듈 설명 참고). 같은 후보·같은 시드면 항상 같은 순서."""
    rng = random.Random(seed)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in sorted(candidates(rows), key=lambda r: r["cid"]):
        groups.setdefault((r.get("sd") or "", r.get("sg") or ""), []).append(r)
    keys = sorted(groups)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(groups[k])
    order: list[dict[str, Any]] = []
    for i in range(max((len(v) for v in groups.values()), default=0)):
        order += [groups[k][i] for k in keys if i < len(groups[k])]
    return order


@lru_cache(maxsize=1)
def _order() -> tuple[dict[str, Any], ...]:
    if not tour_intro.PATH.exists():
        return ()
    return tuple(build_order(json.loads(tour_intro.PATH.read_text(encoding="utf-8"))))


def pick_for(day: date, order: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None) -> dict[str, Any] | None:
    """그날의 장소 (응답 모양). 후보가 없으면 None."""
    seq = _order() if order is None else order
    if not seq:
        return None
    r = seq[(day - PICK_EPOCH).days % len(seq)]
    region = " ".join(x for x in (r.get("sd"), r.get("sg")) if x)
    return {
        "date": day.isoformat(),
        "content_id": r["cid"],
        "name": r["n"],
        "sido": r.get("sd") or "",
        "sigungu": r.get("sg") or "",
        "region": region,
        "description": r.get("desc") or "",
        "image": tour_intro.https_image(r.get("img")),
        "lat": r["lat"],
        "lng": r["lng"],
        "kakao_map_url": f"https://map.kakao.com/link/map/{quote(r['n'].replace(',', ' '), safe='')},{r['lat']},{r['lng']}",
        "source": SOURCE,
    }
