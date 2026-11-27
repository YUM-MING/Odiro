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
from odiro.data.ingest.common import STATE_DIR, TOUR_DIR, read_jsonl
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
# 물놀이 위주 장소 (추운 달에는 daily_pick 이 건너뛴다). ① 분류 코드 ② 없으면 이름. 폭포는 겨울 빙폭 관광이 있어 넣지 않는다.
# 2026-11 수집분 확인: lclsSystm3 NA010400 = 계곡(하천), NA020900 = 해수욕장·해변 / 옛 cat3 A01010900 = 계곡, A01011200 = 해수욕장.
# 워터파크·물놀이장은 분류가 제각각이라 이름으로만 본다
WET_LCLS3 = frozenset({"NA010400", "NA020900"})
WET_CAT3 = frozenset({"A01010900", "A01011200"})
WET_NAME_WORDS = ("계곡", "해수욕장", "해변", "물놀이장", "워터파크")
# 주소 첫 단어 → 짧은 시도 이름. 전남·광주는 법정동 코드가 하나(12)라 주소로 나눈다.
# 통합 뒤 주소는 둘 다 "전남광주통합특별시 …" 로 시작해 접두어로는 못 가른다 → 시군구가 '구'(광주 자치구)면 광주, 시·군이면 전남
_SIDO_BY_ADDR = (("광주", "광주"), ("전라남도", "전남"), ("전남", "전남"))
_SENTENCE_END = re.compile(r"(?<=[.!?。])\s+")
# 주소에서 시도 단어 (긴 이름·짧은 이름·특별자치도 모두: 전라남도/전남/전남광주통합특별시, 전북특별자치도/전라북도/전북, 강원특별자치도/강원 …)
_SIDO_TOKEN = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주)")
_SIGUNGU_END = ("시", "군", "구")
# 공식 시군구 코드표 (tour_api.fetch_sigungu 가 남긴 것: 지금은 수도권만 있다)
SIGUNGU_DIRS = (ROOT / "data" / "sigungu", STATE_DIR)


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


def sido_short(code: str, addr: str, sg: str = "") -> str:
    """짧은 시도 이름. 12(전남·광주)는 시군구로 가른다: '구'면 광주(전남에는 구가 없다), 그 밖에는 주소 접두어, 기본 전남."""
    if code == "12":
        if sg.endswith("구"):
            return "광주"
        for prefix, name in _SIDO_BY_ADDR:
            if addr.startswith(prefix) and not addr.startswith("전남광주"):
                return name
        return "전남"
    return regions.SIDO.get(code, "")


def sigungu_name(addr: str) -> str:
    """주소에서 시군구 이름. 시도 단어(긴 이름·짧은 이름·특별자치도) 바로 뒤의 시·군·구, 시도 없이 시군구로 시작하면 첫 단어.
    예) '전라남도 곡성군 …'·'전남 곡성군 …'·'전남광주통합특별시 곡성군 …'·'곡성군 곡성읍 …' → '곡성군'. 세종처럼 없으면 빈 문자열."""
    parts = addr.split()
    for i, t in enumerate(parts):
        if _SIDO_TOKEN.match(t):  # 앞에 '닫기' 같은 잡음이 붙어 있어도 시도 단어부터 본다
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            return nxt if nxt.endswith(_SIGUNGU_END) else ""
    return parts[0] if parts and parts[0].endswith(_SIGUNGU_END) else ""


def official_sigungu() -> dict[tuple[str, str], str]:
    """공식 코드표 (시도코드, 시군구코드) → 이름 첫 단어 ('수원시 장안구' → '수원시', 주소에서 뽑은 이름과 같은 단위)."""
    out: dict[tuple[str, str], str] = {}
    for folder in SIGUNGU_DIRS:
        for f in sorted(folder.glob("sigungu_*.json")) if folder.exists() else []:
            sido = f.stem.split("_", 1)[1]
            for sg in json.loads(f.read_text(encoding="utf-8")):
                if sg.get("code") and sg.get("name"):
                    out.setdefault((sido, str(sg["code"])), sg["name"].split()[0])
    return out


def code_sigungu(areas: dict[str, dict[str, dict[str, Any]]]) -> dict[tuple[str, str], str]:
    """시군구 코드 → 이름. ① 공식 코드표 ② 같은 코드를 가진 장소들의 주소에서 가장 많이 나온 이름 (시도 단어가 있는 주소만 센다)."""
    names = official_sigungu()
    votes: dict[tuple[str, str], Counter] = {}
    for code, meta in areas.items():
        for p in meta.values():
            key = (p.get("sido_code") or code, str(p.get("sigungu_code") or ""))
            addr = p.get("addr") or ""
            if key in names or not key[1] or not any(_SIDO_TOKEN.match(t) for t in addr.split()[:2]):
                continue
            if sg := sigungu_name(addr):
                votes.setdefault(key, Counter())[sg] += 1
    for key, c in votes.items():
        names.setdefault(key, c.most_common(1)[0][0])
    return names


def region_of(p: dict[str, Any], code: str, names: dict[tuple[str, str], str]) -> tuple[str, str]:
    """(짧은 시도, 시군구). 시군구는 ① 코드 기반 이름 ② 주소 파싱. 못 얻으면 시군구는 빈 문자열."""
    sido_code = p.get("sido_code") or code
    addr = p.get("addr") or ""
    sg = names.get((sido_code, str(p.get("sigungu_code") or ""))) or sigungu_name(addr)
    return sido_short(sido_code, addr, sg), sg


def is_wet_place(p: dict[str, Any]) -> bool:
    """물놀이 위주 장소인지 (계곡·해수욕장·해변·물놀이장·워터파크). 이름에 '폭포'가 있으면 아니다."""
    name = p.get("title") or p.get("n") or ""
    if "폭포" in name:
        return False
    if (p.get("lcls3") or "") in WET_LCLS3 or (p.get("cat3") or "") in WET_CAT3:
        return True
    return any(w in name for w in WET_NAME_WORDS)


def is_metro_district(sd: str, sg: str) -> bool:
    """광역시의 자치구인지 (예: 대구 중구 → True, 대구 달성군 → False, 경북 포항시 → False)."""
    return sd in PICK_METRO_SIDO and sg.endswith("구")


# 시도는 있으나 시군구를 못 얻어 후보에서 뺀 수 (시도별, main 에서 보고)
SKIPPED_NO_SIGUNGU: Counter = Counter()
NO_SIGUNGU_SIDO = frozenset({"세종"})  # 시군구가 없는 시도 (세종은 시 하나라 지역 = 세종)


def pick_fields(p: dict[str, Any], overview: str, code: str, names: dict[tuple[str, str], str] | None = None) -> dict[str, Any] | None:
    """후보면 더할 필드, 아니면 None."""
    sido_code = p.get("sido_code") or code
    if sido_code in PICK_EXCLUDED_SIDO or not is_pick_kind(p):
        return None
    if not https_image(p.get("image")):  # 배너는 큰 사진(firstimage)을 쓴다
        return None
    overview = clean_text(overview)
    if len(overview) < PICK_MIN_OVERVIEW:
        return None
    sd, sg = region_of(p, code, names or {})
    if not sd:
        return None
    if not sg and sd not in NO_SIGUNGU_SIDO:
        # 시도만으로는 '이 지역으로 코스 만들기'가 너무 넓고 시군구별 골고루 뽑기가 깨진다 → 후보에서 뺀다 (조회 줄은 유지)
        SKIPPED_NO_SIGUNGU[sd] += 1
        return None
    if is_metro_district(sd, sg):
        return None
    return {"pick": 1, "cid": p["content_id"], "sd": sd, "sg": sg, "desc": short_desc(overview), **({"wet": 1} if is_wet_place(p) else {})}


def build() -> list[dict]:
    """장소마다 한 줄: 이름·좌표 + 이용 정보(있는 항목만) + 대표 이미지 img(있으면, https).
    이용 정보가 없어도 이미지가 있으면 넣는다 (지도 정보 창 이미지용). 둘 다 없으면 넣지 않는다.
    숨은 여행지 후보면 pick·cid·sd·sg·desc 를 더한다."""
    rows: list[dict] = []
    SKIPPED_NO_SIGUNGU.clear()
    # 갱신은 뒤에 덧붙이므로 같은 장소가 여러 줄일 수 있다 → 마지막 줄만
    areas = {path.stem.removeprefix("area_"): {p["content_id"]: p for p in read_jsonl(path)} for path in sorted(TOUR_DIR.glob("area_*.jsonl"))}
    names = code_sigungu(areas)
    for code, meta in areas.items():
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
            pick = pick_fields(p, overviews.get(cid, ""), code, names)
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
          f"시군구 {len({(r['sd'], r['sg']) for r in picks})}곳 · 물놀이 장소(추운 달 제외) {sum(1 for r in picks if r.get('wet'))}곳")
    by_sd: dict[str, set] = {}
    for r in picks:
        by_sd.setdefault(r["sd"], set()).add(r["sg"])
    for sd, n in Counter(r["sd"] for r in picks).most_common():
        print(f"  {sd}: 후보 {n}곳 · 시군구 {len(by_sd[sd])}곳 · 시군구를 못 얻어 제외 {SKIPPED_NO_SIGUNGU.get(sd, 0)}곳")
    for sd, n in SKIPPED_NO_SIGUNGU.items():
        if sd not in by_sd:
            print(f"  {sd}: 후보 0곳 · 시군구를 못 얻어 제외 {n}곳")


if __name__ == "__main__":
    main()
