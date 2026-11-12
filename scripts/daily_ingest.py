"""하루 한 번 돌리는 TourAPI 상세 수집 루틴 (수집 → 라벨링 → 인덱스).

    python scripts/daily_ingest.py            # 오늘 한도만큼 수집하고 라벨링·인덱스까지
    python scripts/daily_ingest.py --status   # 시도별 진행 현황만 출력 (API 호출 없음)
    python scripts/daily_ingest.py --no-index # 수집만 (라벨링·임베딩 비용 없이)
    python scripts/daily_ingest.py --daily-limit 10000   # 기본 키가 운영계정으로 승인돼 한도가 올랐을 때
    python scripts/daily_ingest.py --types 12 14 39 28 15 32 25   # 쇼핑(38)을 빼고 받기

순서: 서울 → 인천 → 경기 → 나머지 시도. 앞 지역이 끝나야 다음 지역으로 넘어간다.
한도: TourAPI 개발계정은 키마다 상세 조회 일 1,000건. `.env` 의 TOUR_API_KEY 를 먼저 쓰고
      TOUR_API_KEYS_EXTRA(쉼표 구분) 의 키를 이어 쓴다 → 키 3개면 하루 약 3,000건.
      한도는 자정(한국 시간)에 초기화되고, 이미 받은 건 건너뛰므로 여러 번 실행해도 안전하다.
비용: 라벨링(gpt-4o-mini)·임베딩이 OPENAI_API_KEY 로 나간다. 장소 3,000건 ≈ 300~500원.

배포 사이트에는 자동 반영되지 않는다. 반영하려면 docs/HANDOVER.md 의 "벡터 DB 올리기" 를 따른다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from odiro.data.ingest import regions
from odiro.data.ingest.common import TOUR_DIR

# 서울 → 인천 → 경기 → 나머지 시도 (regions.SIDO 정의 순서)
ORDER: list[str] = [*regions.CAPITAL_AREA, *regions.OTHER_AREAS]


def _lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def status() -> list[tuple[str, int, int]]:
    """[(시도코드, 메타 건수, 상세 건수)]. 메타가 0 이면 아직 메타를 받지 않은 시도."""
    return [(c, _lines(TOUR_DIR / f"area_{c}.jsonl"), _lines(TOUR_DIR / f"detail_{c}.jsonl")) for c in ORDER]


def print_status() -> None:
    rows = status()
    print(f"{'시도':<8}{'상세/메타':>16}  진행")
    for code, meta, detail in rows:
        name = regions.sido_name(code)
        if not meta:
            print(f"{name:<8}{'메타 없음':>16}")
            continue
        pct = 100 * detail / meta
        print(f"{name:<8}{detail:>8,}/{meta:<7,}  {pct:5.1f}%{'  ✔' if detail >= meta * 0.995 else ''}")
    got, total = sum(r[2] for r in rows), sum(r[1] for r in rows)
    print(f"{'합계':<8}{got:>8,}/{total:<7,}  (메타를 받은 시도 기준)")


def run(module: str, *args: str) -> None:
    cmd = [sys.executable, "-m", module, *args]
    print(f"\n$ python -m {module} {' '.join(args)}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="진행 현황만 출력")
    ap.add_argument("--no-index", action="store_true", help="수집만 하고 라벨링·인덱스는 건너뜀")
    ap.add_argument("--capital-only", action="store_true", help="수도권(서울·인천·경기)만. 나머지 시도 메타를 받지 않는다")
    ap.add_argument("--daily-limit", type=int, default=None, help="기본 키(TOUR_API_KEY)의 일일 한도. 운영계정 승인 후 올린다 (추가 키는 1,000 고정)")
    ap.add_argument("--types", nargs="*", default=None, help="받을 콘텐츠타입 코드 (기본: 전부). 12 관광지 14 문화시설 15 행사 25 여행코스 28 레포츠 32 숙박 38 쇼핑 39 음식점")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if args.status:
        print_status()
        return

    order = list(regions.CAPITAL_AREA) if args.capital_only else ORDER
    before = {c: d for c, _, d in status()}

    # 1) 아직 메타가 없는 시도는 메타부터 (시도당 호출 10~20회, 한도와 무관하게 금방 끝난다)
    missing = [c for c, meta, _ in status() if c in order and not meta]
    if missing:
        run("odiro.data.ingest.tour_api", "--area", *missing, "--no-detail")

    # 2) 상세: 순서대로, 오늘 한도가 다 찰 때까지
    extra = (["--daily-limit", str(args.daily_limit)] if args.daily_limit else []) + (["--types", *args.types] if args.types else [])
    run("odiro.data.ingest.tour_api", "--area", *order, "--no-meta", *extra)

    after = {c: d for c, _, d in status()}
    changed = [c for c in order if after[c] > before[c]]
    print("\n오늘 받은 상세:", ", ".join(f"{regions.sido_name(c)} +{after[c] - before[c]:,}" for c in changed) or "없음 (한도 소진 또는 전부 완료)")

    # 3) 새로 받은 시도만 라벨링 → 인덱스
    if changed and not args.no_index:
        run("odiro.data.ingest.labeling", "--area", *changed, "--only", "place")
        run("odiro.data.ingest.build_index", "--area", *changed)

    print()
    print_status()


if __name__ == "__main__":
    main()
