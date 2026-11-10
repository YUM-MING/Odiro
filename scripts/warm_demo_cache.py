"""시연 시나리오 3개를 미리 실행해 결과를 캐시에 넣는다 (PLAN.md 8-1, D9).

같은 요청(지역·날짜·조건이 동일)이 들어오면 네트워크 없이 캐시 결과를 돌려주므로,
시연 당일 사용할 날짜로 미리 돌려두면 LLM·지도 API 가 죽어도 데모가 된다.

실행:
    python scripts/warm_demo_cache.py --date 2026-11-29           # 시연 날짜
    python scripts/warm_demo_cache.py --date 2026-11-29 --force   # 캐시 무시하고 다시 생성
결과 JSON 은 cache/demo/*.json 에도 저장한다 (프론트 목업·발표 자료용).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from odiro.agent.run import run_course
from odiro.api.schemas import CourseRequest, TraceStep
from odiro.config import settings

SCENARIOS: dict[str, dict] = {
    "seongsu_date": {
        "mode": "outing", "transport": "walk", "region": "성수동", "start_time": "13:00", "end_time": "21:00",
        "budget": 100_000, "moods": ["감성/조용한", "사진맛집", "웨이팅적은"], "party": "연인",
        "free_text": "사람 적고 분위기 있는 곳",
    },
    "gapyeong_trip": {
        "mode": "trip", "transport": "car", "region": "가평", "days": 2, "start_time": "10:00", "end_time": "21:00",
        "budget": 200_000, "moods": ["뷰맛집/일몰", "감성/조용한", "자연/산책"], "party": "연인",
        "free_text": "일출 명소와 주차 편한 맛집, 북한강 드라이브",
    },
    "songdo_family": {
        "mode": "outing", "transport": "car", "region": "인천 송도", "start_time": "10:00", "end_time": "18:00",
        "budget": 150_000, "moods": ["아이동반", "실내(비오는날)"], "party": "가족(아이 2명)",
        "free_text": "비 오면 실내 대안, 아이 동반 가능한 식당",
    },
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="시연 날짜 YYYY-MM-DD")
    ap.add_argument("--only", nargs="*", choices=list(SCENARIOS), default=list(SCENARIOS))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    out_dir = settings.cache_dir / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in args.only:
        req = CourseRequest(date=args.date, **SCENARIOS[key])
        print(f"\n=== {key}: {req.region} {req.mode}/{req.transport} {req.date}")

        def progress(step: TraceStep) -> None:
            if step.status != "start":
                print(f"  ✓ {step.node:<16} {step.ms:>6}ms {step.detail}")

        resp = run_course(req, progress, use_cache=not args.force)
        path = out_dir / f"{key}.json"
        path.write_text(resp.model_dump_json(indent=2), encoding="utf-8")
        print(f"  → {len(resp.places)}곳, {resp.meta.elapsed_ms / 1000:.1f}s{' (캐시)' if resp.meta.cached else ''}, 저장 {path}")
        if not resp.places:
            print("  ⚠ 장소 0곳 — --force 로 다시 생성하세요")


if __name__ == "__main__":
    main()
