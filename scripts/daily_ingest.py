"""하루 한 번 돌리는 TourAPI 상세 수집 루틴 (수집 → 라벨링 → 인덱스).

    python scripts/daily_ingest.py            # 오늘 한도만큼 수집하고 라벨링·인덱스까지
    python scripts/daily_ingest.py --status   # 시도별 진행 현황만 출력 (API 호출 없음)
    python scripts/daily_ingest.py --no-intro # 이용 정보(detailIntro2) 수집은 건너뜀 (기본은 상세 뒤에 한도 끝까지 수집)
    python scripts/daily_ingest.py --no-index # 수집만 (라벨링·임베딩 비용 없이)
    python scripts/daily_ingest.py --daily-limit 10000   # 기본 키가 운영계정으로 승인돼 한도가 올랐을 때
    python scripts/daily_ingest.py --types 12 14 39 28 15 32 25   # 쇼핑(38)을 빼고 받기
    python scripts/daily_ingest.py --no-sync  # 변경·삭제 갱신(목록 재비교)을 건너뜀
    python scripts/daily_ingest.py --force-removal   # 한 번에 5% 넘는 삭제도 허용 (실제 대량 삭제를 확인한 뒤에만)

변경·삭제 갱신: 하루 한 번 시도별 목록을 새로 받아 저장된 목록과 장소별 modified 를 비교한다.
      바뀐 장소는 상세·이용 정보를 다시 받고 라벨·임베딩을 다시 만들고, 사라진 장소는 모든 저장소에서 지운다.
      자세한 규칙과 안전장치는 odiro/data/ingest/sync.py. 갱신이 중단되면 종료 코드 1 (자동화는 업로드·배포를 멈춘다).

순서: 서울 → 인천 → 경기 → 나머지 시도. 앞 지역이 끝나야 다음 지역으로 넘어간다.
한도: TourAPI 개발계정은 키마다 상세 조회 일 1,000건. `.env` 의 TOUR_API_KEY 를 먼저 쓰고
      TOUR_API_KEYS_EXTRA(쉼표 구분) 의 키를 이어 쓴다 → 키 3개면 하루 약 3,000건.
      한도는 자정(한국 시간)에 초기화되고, 이미 받은 건 건너뛰므로 여러 번 실행해도 안전하다.
비용: 라벨링(gpt-4o-mini)·임베딩이 OPENAI_API_KEY 로 나간다. 장소 3,000건 ≈ 300~500원.

배포는 GitHub Actions(daily-ingest.yml)가 이어서 한다. 손으로 돌렸다면 docs/HANDOVER.md 의 "벡터 DB 올리기" 를 따른다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from odiro.data.ingest import regions, sync
from odiro.data.ingest.common import TOUR_DIR, QuotaExceeded, RetryableHTTPError, setup_logging

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


def sync_areas(areas: list[str], types: list[int], daily_limit: int | None, force: bool) -> list[str]:
    """시도별 목록을 새로 받아 저장된 목록과 비교·반영한다. 중단된 시도의 사유 목록을 돌려준다 (하루 한 번만)."""
    from odiro.data.ingest.tour_api import DEV_DAILY_LIMIT, TourClient, fetch_meta

    client = TourClient(daily_limit=daily_limit or DEV_DAILY_LIMIT)
    failures: list[str] = []
    for code in areas:
        name = regions.sido_name(code)
        if not (TOUR_DIR / f"area_{code}.jsonl").exists() or sync.synced_today(code):
            continue
        try:
            res = sync.apply_sync(code, fetch_meta(client, code, types), types, force)
        except (sync.SyncAborted, RetryableHTTPError, QuotaExceeded) as e:
            failures.append(f"{name}: {e}")
            print(f"[갱신 중단] {name}: {e}", flush=True)
            continue
        sync.mark_synced(code)
        print(f"[갱신] {name}: 신규 {res.added:,} · 변경 {res.changed:,} · 삭제 {res.removed:,}", flush=True)
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="진행 현황만 출력")
    ap.add_argument("--no-index", action="store_true", help="수집만 하고 라벨링·인덱스는 건너뜀")
    ap.add_argument("--no-intro", action="store_true", help="이용 정보(휴무일·시간·요금·주차) 수집 건너뜀")
    ap.add_argument("--no-sync", action="store_true", help="변경·삭제 갱신(목록 재비교)을 건너뜀")
    ap.add_argument("--force-removal", action="store_true", help="한 번에 저장 건수의 5%% 넘는 삭제도 반영 (대량 삭제가 사실인지 확인한 뒤에만)")
    ap.add_argument("--capital-only", action="store_true", help="수도권(서울·인천·경기)만. 나머지 시도 메타를 받지 않는다")
    ap.add_argument("--daily-limit", type=int, default=None, help="기본 키(TOUR_API_KEY)의 일일 한도. 운영계정 승인 후 올린다 (추가 키는 1,000 고정)")
    ap.add_argument("--types", nargs="*", default=None, help="받을 콘텐츠타입 코드 (기본: 전부). 12 관광지 14 문화시설 15 행사 25 여행코스 28 레포츠 32 숙박 38 쇼핑 39 음식점")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if args.status:
        print_status()
        return

    setup_logging()
    order = list(regions.CAPITAL_AREA) if args.capital_only else ORDER
    all_types = args.types or list(regions.CONTENT_TYPES)
    before = {c: d for c, _, d in status()}
    failures: list[str] = []

    # 0) 지난번에 못 지운 라벨·벡터 정리 (먼저. 뒤에서 새로 만든 것까지 지우지 않게)
    if not args.no_index:
        run("odiro.data.ingest.sync", "--purge", "--area", *order)

    # 1) 아직 메타가 없는 시도는 메타부터 (시도당 호출 10~20회, 한도와 무관하게 금방 끝난다)
    missing = [c for c, meta, _ in status() if c in order and not meta]
    if missing:
        run("odiro.data.ingest.tour_api", "--area", *missing, "--no-detail")
        for c in missing:
            sync.mark_synced(c)  # 방금 새로 받았으니 오늘은 비교할 것이 없다

    # 1-2) 변경·삭제 갱신: 목록을 새로 받아 비교. 삭제는 즉시 반영, 변경은 아래 수집 단계가 다시 받는다
    if not args.no_sync:
        failures = sync_areas(order, all_types, args.daily_limit, args.force_removal)
        if not args.no_index:
            run("odiro.data.ingest.sync", "--purge", "--area", *order)

    # 2) 상세: 순서대로, 오늘 한도가 다 찰 때까지 (신규 + 변경)
    extra = (["--daily-limit", str(args.daily_limit)] if args.daily_limit else []) + (["--types", *args.types] if args.types else [])
    run("odiro.data.ingest.tour_api", "--area", *order, "--no-meta", *extra)

    # 2-2) 이용 정보(detailIntro2): 상세와 별도 한도라 항상 한도 끝까지. 소개글이 있는 시도만 (신규 + 변경)
    if not args.no_intro:
        intro_areas = [c for c in order if (TOUR_DIR / f"detail_{c}.jsonl").exists()]
        if intro_areas:
            intro_before = {c: _lines(TOUR_DIR / f"intro_{c}.jsonl") for c in intro_areas}
            run("odiro.data.ingest.tour_api", "--area", *intro_areas, "--intro-only")
            got = {c: _lines(TOUR_DIR / f"intro_{c}.jsonl") - intro_before[c] for c in intro_areas}
            print("오늘 받은 이용 정보:", ", ".join(f"{regions.sido_name(c)} +{n:,}" for c, n in got.items() if n) or "없음 (한도 소진 또는 전부 완료)")
    # 서버용 조회 파일은 삭제·변경이 반영되도록 항상 다시 만든다
    subprocess.run([sys.executable, "scripts/build_intro_lookup.py"], cwd=ROOT, check=True)

    after = {c: d for c, _, d in status()}
    changed = [c for c in order if after[c] > before[c]]
    print("\n오늘 받은 상세(신규 포함):", ", ".join(f"{regions.sido_name(c)} +{after[c] - before[c]:,}" for c in changed) or "줄 수 증가 없음 (갱신 덮어쓰기는 줄 수에 안 잡힘)")

    # 3) 라벨링 → 인덱스. 다시 받은 장소의 옛 라벨·벡터를 먼저 지우고(큐), 빠진 것만 만든다 (이미 있는 건 건너뜀)
    if not args.no_index:
        build_areas = [c for c in order if (TOUR_DIR / f"detail_{c}.jsonl").exists()]
        if build_areas:
            run("odiro.data.ingest.sync", "--purge", "--area", *build_areas)
            run("odiro.data.ingest.labeling", "--area", *build_areas, "--only", "place")
            run("odiro.data.ingest.build_index", "--area", *build_areas)

    print()
    print_status()
    if failures:
        print("\n갱신이 중단된 시도가 있어 실패로 끝냅니다 (업로드·배포 금지):", *failures, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
