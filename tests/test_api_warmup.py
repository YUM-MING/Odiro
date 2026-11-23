"""서버 시작 예열 (F1). 실제 벡터 DB·외부 API 는 쓰지 않는다 (모의 객체)."""

import threading

from fastapi.testclient import TestClient

from odiro.api import main
from odiro.tools import rag_search, tour_intro


def _client(monkeypatch, warm, env="1", wait=5):
    if env is None:
        monkeypatch.delenv(main.WARMUP_ENV, raising=False)
    else:
        monkeypatch.setenv(main.WARMUP_ENV, env)
    monkeypatch.setattr(main, "WARMUP_WAIT_SEC", wait)
    monkeypatch.setattr(rag_search, "warm", warm)
    monkeypatch.setattr(tour_intro, "_table", dict)
    main.warmup_state.update(status="off", ms=0, error="")
    return TestClient(main.app)


def test_startup_hook_runs_warmup_before_serving(monkeypatch):
    calls = []
    with _client(monkeypatch, lambda: calls.append("warm") or {"docs": 1}) as c:
        assert calls == ["warm"]  # 포트를 열기 전(시작 단계)에 이미 불렸다
        body = c.get("/api/health").json()
        assert body["status"] == "ok" and body["warmup"] == "done" and "version" in body


def test_warmup_failure_does_not_stop_server(monkeypatch):
    def boom():
        raise RuntimeError("chroma 없음")

    with _client(monkeypatch, boom) as c:
        body = c.get("/api/health").json()
        assert body["status"] == "ok" and body["warmup"] == "error"
        assert "chroma 없음" in main.warmup_state["error"]
        assert c.get("/api/moods").status_code == 200


def test_requests_served_while_slow_warmup_continues(monkeypatch):
    release = threading.Event()

    def slow():
        release.wait(5)
        return {"docs": 1}

    with _client(monkeypatch, slow, wait=0.2) as c:  # 0.2초만 기다리고 서버를 연다
        assert c.get("/api/health").json()["warmup"] == "running"
        assert c.get("/api/moods").status_code == 200  # 예열 중에도 요청 처리
        release.set()


def test_warmup_off_without_env(monkeypatch):
    calls = []
    with _client(monkeypatch, lambda: calls.append("warm"), env=None) as c:
        assert calls == [] and c.get("/api/health").json()["warmup"] == "off"
