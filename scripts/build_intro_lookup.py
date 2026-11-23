"""TourAPI 이용 정보(intro_*.jsonl) + 메타(area_*.jsonl) → 서버가 읽는 조회 파일 data/tour_intro.json.

data/raw 는 배포에 올라가지 않으므로, 서버가 쓸 최소한(이름·좌표·이용 정보)만 따로 모아 git 에 포함한다.

    python scripts/build_intro_lookup.py          # 수집을 돌린 뒤 다시 실행 (덮어쓰기)

값이 하나도 없는 장소는 넣지 않는다. 반려동물은 거의 비어 있어 넣지 않는다 (PROGRESS_DETAILINTRO 채움률 표).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from odiro.data.ingest.common import TOUR_DIR, read_jsonl
from odiro.tools.tour_intro import https_image

OUT = ROOT / "data" / "tour_intro.json"
FIELDS = ("rest_date", "use_time", "use_fee", "parking", "parking_fee")


def build() -> list[dict]:
    """장소마다 한 줄: 이름·좌표 + 이용 정보(있는 항목만) + 대표 이미지 img(있으면, https).
    이용 정보가 없어도 이미지가 있으면 넣는다 (지도 정보 창 이미지용). 둘 다 없으면 넣지 않는다."""
    rows: list[dict] = []
    for area_path in sorted(TOUR_DIR.glob("area_*.jsonl")):
        code = area_path.stem.removeprefix("area_")
        # 갱신은 뒤에 덧붙이므로 같은 장소가 여러 줄일 수 있다 → 마지막 줄만
        meta = {p["content_id"]: p for p in read_jsonl(area_path)}
        intro_path = TOUR_DIR / f"intro_{code}.jsonl"
        latest = {r["content_id"]: r for r in read_jsonl(intro_path)} if intro_path.exists() else {}
        for cid, p in meta.items():
            if p.get("lat") is None or p.get("lng") is None:
                continue
            r = latest.get(cid, {})
            vals = {k: r[k] for k in FIELDS if r.get(k)}
            # firstimage(약 500x333, 정보 창 폭 420px 에 맞음). 없을 때만 썸네일 firstimage2(약 150x100)
            img = https_image(p.get("image") or p.get("image_thumb"))
            if not vals and not img:
                continue
            rows.append({"n": p["title"], "lat": round(p["lat"], 5), "lng": round(p["lng"], 5), **vals, **({"img": img} if img else {})})
    return rows


def main() -> None:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows):,}건 → {OUT} ({OUT.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
