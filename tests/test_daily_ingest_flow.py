"""scripts/daily_ingest.py 실행 순서 테스트 (외부 호출은 전부 가짜)."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "daily_ingest.py"


@pytest.fixture
def di(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("daily_ingest_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TOUR_DIR", tmp_path)
    (tmp_path / "area_11.jsonl").write_text('{"content_id":"1"}\n', encoding="utf-8")
    (tmp_path / "detail_11.jsonl").write_text('{"content_id":"1"}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "ORDER", ["11"])
    monkeypatch.setattr(mod.sync, "mark_synced", lambda c: None)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: None)
    return mod


def run_main(di, monkeypatch, *argv, failures=()):
    calls: list[str] = []
    monkeypatch.setattr(di, "run", lambda module, *a: calls.append(module.rsplit(".", 1)[-1] + (" " + a[0] if a and module.endswith("sync") else "")))
    monkeypatch.setattr(di, "sync_areas", lambda *a, **k: (calls.append("SYNC"), list(failures))[1])
    monkeypatch.setattr(sys, "argv", ["daily_ingest.py", *argv])
    code = 0
    try:
        di.main()
    except SystemExit as e:
        code = int(e.code or 0)
    return calls, code


def test_order_purge_before_label_and_index(di, monkeypatch):
    calls, code = run_main(di, monkeypatch)
    assert code == 0
    # 정리(--purge) → 목록 비교 → 정리 → 상세 → 이용 정보 → 정리 → 라벨링 → 인덱스
    assert calls == ["sync --purge", "SYNC", "sync --purge", "tour_api", "tour_api", "sync --purge", "labeling", "build_index"]


def test_sync_failure_exits_nonzero_but_finishes(di, monkeypatch):
    calls, code = run_main(di, monkeypatch, failures=["서울: 삭제 한도 초과"])
    assert code == 1  # 자동화가 업로드·배포를 멈추게
    assert calls[-1] == "build_index"  # 나머지 수집은 끝까지 진행


def test_no_sync_and_no_index(di, monkeypatch):
    calls, code = run_main(di, monkeypatch, "--no-sync", "--no-index")
    assert code == 0 and calls == ["tour_api", "tour_api"]
