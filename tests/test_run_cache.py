"""run_course 의 결과 캐시와 refresh('다시 만들기') 동작. 네트워크·LLM 없이 그래프 실행을 가짜로 바꿔 확인한다."""

from odiro.agent import run as run_mod
from odiro.api.schemas import CourseRequest


class _FakeCache(dict):
    def set(self, key, value, expire=None):  # diskcache 인터페이스
        self[key] = value


def _setup(monkeypatch):
    calls = {"n": 0}
    fake = _FakeCache()

    def fake_stream(g, state, sequence, on_progress):
        calls["n"] += 1
        place = {"order": 1, "day": 1, "name": f"장소{calls['n']}", "lat": 37.5, "lng": 127.0, "verified": True}
        return {**state, "title": f"코스{calls['n']}", "places": [place], "legs": [], "final_answer": "**Odiro:** 안녕"}

    monkeypatch.setattr(run_mod, "cache", lambda: fake)
    monkeypatch.setattr(run_mod, "graph", lambda: None)
    monkeypatch.setattr(run_mod, "_stream", fake_stream)
    return calls


REQ = CourseRequest(region="성수동", date="2026-11-15")


def test_same_request_hits_cache(monkeypatch):
    calls = _setup(monkeypatch)
    first = run_mod.run_course(REQ)
    second = run_mod.run_course(REQ)
    assert calls["n"] == 1
    assert second.meta.cached is True
    assert second.title == first.title


def test_refresh_skips_cache_and_updates_it(monkeypatch):
    calls = _setup(monkeypatch)
    run_mod.run_course(REQ)
    fresh = run_mod.run_course(REQ, refresh=True)
    assert calls["n"] == 2  # 캐시가 있어도 다시 생성
    assert fresh.meta.cached is False
    assert fresh.title == "코스2"
    # 새 결과가 캐시에 다시 저장돼 다음 일반 요청은 최신 결과를 받는다
    again = run_mod.run_course(REQ)
    assert again.meta.cached is True
    assert again.title == "코스2"
    assert calls["n"] == 2
