"""TourAPI 이용 정보(intro_*.jsonl) + 메타(area_*.jsonl) → 서버가 읽는 조회 파일 data/tour_intro.json.

data/raw 는 배포에 올라가지 않으므로, 서버가 쓸 최소한(이름·좌표·이용 정보)만 따로 모아 git 에 포함한다.

    python scripts/build_intro_lookup.py          # 수집을 돌린 뒤 다시 실행 (덮어쓰기)

값이 하나도 없는 장소는 넣지 않는다. 반려동물은 거의 비어 있어 넣지 않는다 (PROGRESS_DETAILINTRO 채움률 표).

"오늘의 숨은 여행지" 후보 (GET /api/daily-pick 이 고르는 풀): 관광 수요가 덜 몰리는 시도의 자연·인문 관광지 중
대표 이미지와 소개글(detail_*.jsonl overview)이 있는 곳. 후보 줄에만 pick·cid·sd·sg·desc 를 더한다 (기존 필드는 그대로).
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from odiro.data.ingest import regions
from odiro.data.ingest.common import TOUR_DIR, read_jsonl
from odiro.data.ingest.tour_api import clean_text
from odiro.tools.tour_intro import https_image

OUT = ROOT / "data" / "tour_intro.json"
FIELDS = ("rest_date", "use_time", "use_fee", "parking", "parking_fee")

# ---------- 오늘의 숨은 여행지 후보 ----------
# 관광 수요가 이미 몰리는 지역은 뺀다: 서울·인천·경기(수도권), 부산, 제주. 코드는 regions.SIDO (법정동 시도코드)
PICK_EXCLUDED_SIDO = frozenset({"11", "28", "41", "26", "50"})
# 광역시 도심은 접근성이 좋아 이미 방문이 많음. 지방 소도시·농어촌 중심으로 소개 → 광역시의 자치구(이름이 '구')는 뺀다.
# 광역시 안의 군(대구 달성군·군위군, 울산 울주군 등)과 세종은 남긴다. 판별은 시도 기준(짧은 시도 이름) — 도 소속 시의 구(포항시 남구 등)는 해당 없음.
# 부산도 광역시지만 시도 전체가 위에서 빠진다. 광주는 법정동 코드가 전남과 같아(12) 주소로 나눈 이름으로 본다
PICK_METRO_SIDO = frozenset({"대구", "대전", "울산", "광주"})
PICK_CONTENT_TYPE = 12  # 관광지 (regions.CONTENT_TYPES)
# 옛 분류 cat1: A01 자연, A02 인문. 2026-11 수집분은 cat1 이 대부분 비어 있고(관광지의 약 95%) 새 분류 lclsSystm1 만 채워져 있어,
# cat1 이 비었을 때만 lcls1 로 본다: NA 자연관광, HS 역사관광 (VE 문화시설·EX 체험·SH 쇼핑은 제외)
PICK_CAT1 = frozenset({"A01", "A02"})
PICK_LCLS1 = frozenset({"NA", "HS"})
PICK_MIN_OVERVIEW = 80  # 소개글이 이보다 짧으면 배너에 쓸 설명이 모자란다
PICK_DESC_MAX = 140
# 주소 첫 단어 → 짧은 시도 이름. 전남·광주는 법정동 코드가 하나(12)라 주소로 나눈다
_SIDO_BY_ADDR = (("광주", "광주"), ("전라남도", "전남"), ("전남", "전남"))
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")


def is_pick_kind(p: dict[str, Any]) -> bool:
    if int(p.get("content_type_id") or 0) != PICK_CONTENT_TYPE:
        return False
    cat1 = p.get("cat1") or ""
    return cat1 in PICK_CAT1 if cat1 else (p.get("lcls1") or "") in PICK_LCLS1


def short_desc(overview: str, limit: int = PICK_DESC_MAX) -> str:
    """소개글 앞부분을 문장 단위로 limit 자 이내. 첫 문장부터 넘치면 단어 경계에서 자르고 '…'."""
    text = clean_text(overview)
    out = ""
    for s in _SENTENCE_END.split(text):
        cand = f"{out} {s}".strip()
        if len(cand) > limit:
            break
        out = cand
    if out:
        return out
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.") + "…"


def sido_short(code: str, addr: str) -> str:
    if code == "12":
        for prefix, name in _SIDO_BY_ADDR:
            if addr.startswith(prefix):
                return name
        return "전남"
    return regions.SIDO.get(code, "")


def sigungu_name(addr: str) -> str:
    """주소 두 번째 단어가 시·군·구면 그 이름 (예: '경상북도 경주시 …' → '경주시'). 세종처럼 없으면 빈 문자열."""
    parts = addr.split()
    return parts[1] if len(parts) > 1 and parts[1].endswith(("시", "군", "구")) else ""


def is_metro_district(sd: str, sg: str) -> bool:
    """광역시의 자치구인지 (예: 대구 중구 → True, 대구 달성군 → False, 경북 포항시 → False)."""
    return sd in PICK_METRO_SIDO and sg.endswith("구")


def pick_fields(p: dict[str, Any], overview: str, code: str) -> dict[str, Any] | None:
    """후보면 더할 필드, 아니면 None."""
    sido_code = p.get("sido_code") or code
    if sido_code in PICK_EXCLUDED_SIDO or not is_pick_kind(p):
        return None
    if not https_image(p.get("image")):  # 배너는 큰 사진(firstimage)을 쓴다
        return None
    overview = clean_text(overview)
    if len(overview) < PICK_MIN_OVERVIEW:
        return None
    addr = p.get("addr") or ""
    sd = sido_short(sido_code, addr)
    if not sd:
        return None
    sg = sigungu_name(addr)
    if is_metro_district(sd, sg):
        return None
    return {"pick": 1, "cid": p["content_id"], "sd": sd, "sg": sg, "desc": short_desc(overview)}


def build() -> list[dict]:
    """장소마다 한 줄: 이름·좌표 + 이용 정보(있는 항목만) + 대표 이미지 img(있으면, https).
    이용 정보가 없어도 이미지가 있으면 넣는다 (지도 정보 창 이미지용). 둘 다 없으면 넣지 않는다.
    숨은 여행지 후보면 pick·cid·sd·sg·desc 를 더한다."""
    rows: list[dict] = []
    for area_path in sorted(TOUR_DIR.glob("area_*.jsonl")):
        code = area_path.stem.removeprefix("area_")
        # 갱신은 뒤에 덧붙이므로 같은 장소가 여러 줄일 수 있다 → 마지막 줄만
        meta = {p["content_id"]: p for p in read_jsonl(area_path)}
        intro_path = TOUR_DIR / f"intro_{code}.jsonl"
        latest = {r["content_id"]: r for r in read_jsonl(intro_path)} if intro_path.exists() else {}
        detail_path = TOUR_DIR / f"detail_{code}.jsonl"
        overviews = {r["content_id"]: r.get("overview") or "" for r in read_jsonl(detail_path)} if detail_path.exists() else {}
        for cid, p in meta.items():
            if p.get("lat") is None or p.get("lng") is None:
                continue
            r = latest.get(cid, {})
            vals = {k: r[k] for k in FIELDS if r.get(k)}
            # firstimage(약 500x333, 정보 창 폭 420px 에 맞음). 없을 때만 썸네일 firstimage2(약 150x100)
            img = https_image(p.get("image") or p.get("image_thumb"))
            if not vals and not img:
                continue
            pick = pick_fields(p, overviews.get(cid, ""), code)
            rows.append({"n": p["title"], "lat": round(p["lat"], 5), "lng": round(p["lng"], 5), **vals,
                         **({"img": img} if img else {}), **(pick or {})})
    return rows


def main() -> None:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    picks = [r for r in rows if r.get("pick")]
    print(f"{len(rows):,}건 → {OUT} ({OUT.stat().st_size / 1024:.0f}KB)")
    print(f"숨은 여행지 후보 {len(picks):,}곳 · 시도 {dict(Counter(r['sd'] for r in picks).most_common())} · "
          f"시군구 {len({(r['sd'], r['sg']) for r in picks})}곳")


if __name__ == "__main__":
    main()
