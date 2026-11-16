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

from odiro.data.ingest.common import TOUR_DIR, read_jsonl  # noqa: E402

OUT = ROOT / "data" / "tour_intro.json"
FIELDS = ("rest_date", "use_time", "use_fee", "parking", "parking_fee")


def build() -> list[dict]:
    rows: list[dict] = []
    for intro_path in sorted(TOUR_DIR.glob("intro_*.jsonl")):
        code = intro_path.stem.removeprefix("intro_")
        meta = {p["content_id"]: p for p in read_jsonl(TOUR_DIR / f"area_{code}.jsonl")}
        for r in read_jsonl(intro_path):
            p = meta.get(r["content_id"])
            vals = {k: r[k] for k in FIELDS if r.get(k)}
            if not p or not vals or p.get("lat") is None or p.get("lng") is None:
                continue
            rows.append({"n": p["title"], "lat": round(p["lat"], 5), "lng": round(p["lng"], 5), **vals})
    return rows


def main() -> None:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows):,}건 → {OUT} ({OUT.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
