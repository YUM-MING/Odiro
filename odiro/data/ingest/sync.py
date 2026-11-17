"""변경·삭제 갱신: 오늘 받은 목록(areaBasedList2)을 저장된 목록과 비교해 반영한다.

판정은 날짜 비교가 아니라 **장소별 `modified` 값 비교**다.
- 목록의 modified 가 저장된 값과 다르면 → 바뀐 장소. 상세·이용 정보를 다시 받고 라벨링·임베딩을 다시 한다.
- 저장돼 있는데 오늘 목록에 없으면 → 삭제된 장소. detail·intro·라벨·벡터 인덱스에서 모두 지운다.
- 바뀐 장소는 새 정보가 도착할 때까지 **옛 정보를 그대로 서비스**한다 (한도 때문에 며칠 걸릴 수 있어서).
  새 상세가 도착하는 순간에만 옛 라벨·벡터를 지우고 다시 만든다 (purge 큐).

안전장치
- 한 번에 저장된 건수의 5%(최소 30건) 넘게 사라지면 아무것도 지우지 않고 중단한다 (API 오류로 목록이 덜 왔을 때 데이터 보호).
- 목록 수집이 도중에 실패하면 저장된 목록을 건드리지 않는다.
- 지우는 순서는 "파생 데이터 먼저, 목록 마지막"이라 중간에 죽어도 다음 실행이 같은 판정을 이어서 한다.

벡터 인덱스 정리 (build_index 와 같은 Chroma 를 열므로 다른 단계와 프로세스를 분리해서 실행):
    python -m odiro.data.ingest.sync --purge --area 11 28 41
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from odiro.data.ingest import regions
from odiro.data.ingest.common import (
    LABELED_DIR,
    STATE_DIR,
    TOUR_DIR,
    log,
    read_jsonl,
    setup_logging,
    write_jsonl,
)

MAX_REMOVE_RATIO = 0.05
MIN_REMOVE_FLOOR = 30  # 작은 시도(세종 205건 등)에서 몇 건 사라진 걸로 중단하지 않도록


class SyncAborted(Exception):
    """안전장치에 걸려 갱신을 반영하지 않았다."""


# ---------- 파일 유틸 ----------


def rewrite_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """임시 파일에 쓰고 교체한다 (쓰는 도중 죽어도 원본이 남는다)."""
    tmp = path.with_name(path.name + ".tmp")
    write_jsonl(tmp, rows)
    os.replace(tmp, path)


def compact_jsonl(path: Path, key: str = "content_id") -> int:
    """같은 key 가 여러 줄이면 마지막 줄만 남긴다 (갱신은 뒤에 덧붙이기 때문). 지운 줄 수를 돌려준다."""
    if not path.exists():
        return 0
    rows = list(read_jsonl(path))
    last: dict[str, dict[str, Any]] = {}
    for r in rows:
        last[str(r[key])] = r
    dropped = len(rows) - len(last)
    if dropped:
        rewrite_jsonl(path, last.values())
    return dropped


def stamp_legacy(path: Path, modified_by_id: dict[str, str]) -> int:
    """`modified` 가 없는 옛 기록에 '그때 받은 목록의 modified' 를 채운다. 바뀐 줄 수를 돌려준다.

    modified 도입 전에 받은 기록이라 값이 없다. 상세는 목록을 받은 뒤에 받았으므로 그 시점의 목록 값이 기준이 된다.
    """
    if not path.exists():
        return 0
    rows = list(read_jsonl(path))
    n = 0
    for r in rows:
        if "modified" not in r and str(r.get("content_id")) in modified_by_id:
            r["modified"] = modified_by_id[str(r["content_id"])]
            n += 1
    if n:
        rewrite_jsonl(path, rows)
    return n


def drop_ids(path: Path, key: str, ids: set[str]) -> int:
    """key 값이 ids 에 있는 줄을 지운다. 지운 줄 수를 돌려준다."""
    if not ids or not path.exists():
        return 0
    rows = list(read_jsonl(path))
    kept = [r for r in rows if str(r.get(key)) not in ids]
    removed = len(rows) - len(kept)
    if removed:
        rewrite_jsonl(path, kept)
    return removed


# ---------- 비교 ----------


@dataclass
class SyncPlan:
    added: list[str]
    changed: list[str]
    removed: list[str]


def plan_sync(old: Iterable[dict[str, Any]], new: Iterable[dict[str, Any]]) -> SyncPlan:
    old_m = {str(r["content_id"]): r.get("modified") or "" for r in old}
    new_m = {str(r["content_id"]): r.get("modified") or "" for r in new}
    return SyncPlan(
        added=[i for i in new_m if i not in old_m],
        changed=[i for i, m in new_m.items() if i in old_m and old_m[i] != m],
        removed=[i for i in old_m if i not in new_m],
    )


def check_removal_safe(n_old: int, n_new: int, n_removed: int, force: bool = False) -> None:
    if force or not n_removed:
        return
    if n_new == 0:
        raise SyncAborted(f"새 목록이 비어 있음 (저장 {n_old}건) — API 오류로 보고 중단")
    limit = max(MIN_REMOVE_FLOOR, int(n_old * MAX_REMOVE_RATIO))
    if n_removed > limit:
        raise SyncAborted(
            f"삭제 {n_removed}건이 한도({limit}건 = 저장 {n_old}건의 {MAX_REMOVE_RATIO:.0%} 또는 {MIN_REMOVE_FLOOR}건)를 넘음. "
            "실제 대량 삭제가 맞다면 --force-removal 로 다시 실행"
        )


# ---------- purge 큐 (바뀐·삭제된 장소의 라벨·벡터를 지울 목록) ----------


def _queue_path(code: str) -> Path:
    return STATE_DIR / f"purge_{code}.json"


def queue_purge(code: str, ids: Iterable[str]) -> None:
    ids = {str(i) for i in ids}
    if not ids:
        return
    path = _queue_path(code)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        ids |= set(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(sorted(ids)), encoding="utf-8")


def pending_purge(code: str) -> list[str]:
    path = _queue_path(code)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def purge_vectors(vs, ids: list[str], batch: int = 200) -> None:
    """Chroma 에서 이 장소들의 청크를 모두 지운다 (장소 청크는 content_id 메타데이터를 가진다)."""
    col = vs._collection
    for i in range(0, len(ids), batch):
        col.delete(where={"content_id": {"$in": ids[i : i + batch]}})


def process_purge_queue(code: str, vs) -> int:
    """큐에 있는 장소의 라벨·벡터를 지우고 큐를 비운다. 처리한 건수를 돌려준다.

    라벨을 지우면 labeling 이 다시 만들고, 벡터를 지우면 build_index 가 다시 넣는다.
    반드시 labeling/build_index 보다 먼저 실행한다 (끝난 뒤 실행하면 새로 만든 것까지 지운다).
    """
    ids = pending_purge(code)
    if not ids:
        return 0
    drop_ids(LABELED_DIR / f"area_{code}.jsonl", "doc_id", {f"place:{i}" for i in ids})
    purge_vectors(vs, ids)
    _queue_path(code).unlink()
    log.info("%s: 라벨·벡터 정리 %d건", regions.sido_name(code), len(ids))
    return len(ids)


# ---------- 목록 비교 반영 ----------


@dataclass
class SyncResult:
    added: int
    changed: int
    removed: int


def apply_sync(code: str, new_rows: list[dict[str, Any]], types: list[int], force: bool = False) -> SyncResult:
    """새 목록(new_rows, 이번에 받은 types 만 포함)을 저장된 목록과 비교해 반영한다.

    `types` 밖의 콘텐츠타입은 이번에 받지 않았으므로 비교·삭제 대상이 아니고 그대로 둔다.
    """
    meta_path = TOUR_DIR / f"area_{code}.jsonl"
    old = list(read_jsonl(meta_path))
    scope = [r for r in old if r.get("content_type_id") in types]
    kept = [r for r in old if r.get("content_type_id") not in types]

    plan = plan_sync(scope, new_rows)
    check_removal_safe(len(scope), len(new_rows), len(plan.removed), force)

    # 1) 중복 줄 정리, modified 없는 옛 기록에 기준값 채우기 (목록을 덮어쓰기 전에 해야 기준을 잃지 않는다)
    old_mod = {str(r["content_id"]): r.get("modified") or "" for r in old}
    for name in ("detail", "intro"):
        path = TOUR_DIR / f"{name}_{code}.jsonl"
        compact_jsonl(path)
        stamp_legacy(path, old_mod)

    # 2) 삭제: 파생 데이터 → 목록 순. 라벨·벡터는 큐에 넣어 두고 build 단계 직전에 지운다.
    if plan.removed:
        gone = set(plan.removed)
        drop_ids(TOUR_DIR / f"detail_{code}.jsonl", "content_id", gone)
        drop_ids(TOUR_DIR / f"intro_{code}.jsonl", "content_id", gone)
        queue_purge(code, gone)

    # 3) 목록 교체. 바뀐 장소의 옛 detail/intro 는 남겨 두고, modified 가 달라서 다음 수집 때 다시 받게 된다.
    rewrite_jsonl(meta_path, [*kept, *new_rows])
    return SyncResult(len(plan.added), len(plan.changed), len(plan.removed))


# ---------- 하루 한 번 가드 ----------


def synced_today(code: str) -> bool:
    path = STATE_DIR / f"synced_{code}.json"
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("date") == date.today().isoformat()


def mark_synced(code: str) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"synced_{code}.json").write_text(json.dumps({"date": date.today().isoformat()}), encoding="utf-8")


# ---------- CLI ----------


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--purge", action="store_true", help="purge 큐의 라벨·벡터를 지운다")
    ap.add_argument("--area", nargs="*", help="법정동 시도코드 (기본: 수도권)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    setup_logging(args.verbose)
    if not args.purge:
        ap.error("--purge 만 지원합니다 (목록 비교는 scripts/daily_ingest.py 가 호출)")
    codes = [c for c in regions.parse_area_args(args.area, args.all) if pending_purge(c)]
    if not codes:
        log.info("정리할 항목 없음")
        return
    from odiro.data.ingest.build_index import get_vectorstore

    vs = get_vectorstore()
    for code in codes:
        process_purge_queue(code, vs)


if __name__ == "__main__":
    main()
