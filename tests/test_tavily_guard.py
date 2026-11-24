"""T1: Tavily 낭비 줄이기 (실제 호출 없음 — HTTP 클라이언트·캐시를 가짜로 바꾼다)."""

import httpx
import pytest

from odiro.tools import summarize_reviews as sr


class FakeResp:
    def __init__(self, status, body=None, text=""):
        self.status_code, self._body, self.text = status, body or {}, text

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=httpx.Request("POST", sr.TAVILY_URL), response=httpx.Response(self.status_code))


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def post(self, url, json):
        self.calls += 1
        r = self.responses.pop(0) if self.responses else FakeResp(200, {"results": []})
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(sr.settings, "tavily_api_key", "test-key-xyz")
    monkeypatch.setattr(sr, "cached", lambda ns, ttl, fn, *parts: fn())  # 실제 디스크 캐시에 쓰지 않는다
    sr._pause.update(until=0.0, status=0, kind="")
    clock = {"t": 1000.0}
    monkeypatch.setattr(sr, "_now", lambda: clock["t"])
    return clock


def _client(monkeypatch, *responses):
    c = FakeClient(*responses)
    monkeypatch.setattr(sr, "http", lambda: c)
    return c


def test_no_results_skips_llm(monkeypatch):
    _client(monkeypatch)  # 결과 0건
    called = []
    monkeypatch.setattr(sr, "_llm", lambda: called.append(1))
    out = sr.summarize_many([{"name": "가게A", "region": "성수동"}, {"name": "가게B", "region": "성수동"}], "조용한")
    assert out == ["", ""] and called == []


def test_credit_exhausted_pauses_then_resumes(monkeypatch, _isolated):
    c = _client(monkeypatch, FakeResp(432, text='{"detail": {"error": "This request exceeds your plan\'s set usage limit."}}'))
    assert sr.web_search("성수동 카페") == [] and c.calls == 1
    assert sr.web_search("성수동 맛집") == [] and c.calls == 1  # 멈춘 동안은 네트워크 요청 없음
    st = sr.pause_status()
    assert "432" in st and "크레딧·한도 초과" in st and "test-key" not in st and "usage limit" not in st
    _isolated["t"] += sr.PAUSE_SEC + 1  # 10분 뒤 재개
    c.responses.append(FakeResp(200, {"results": [{"title": "t", "url": "u", "content": "c"}]}))
    assert len(sr.web_search("성수동 카페")) == 1 and c.calls == 2 and sr.pause_status() == ""


@pytest.mark.parametrize("status", [401, 403, 433])
def test_auth_or_limit_errors_pause(monkeypatch, status):
    c = _client(monkeypatch, FakeResp(status, text="error"))
    sr.web_search("q1")
    sr.web_search("q2")
    assert c.calls == 1


def test_429_rate_limit_does_not_pause(monkeypatch):
    c = _client(monkeypatch, FakeResp(429, text="Too Many Requests: rate limit of 100 requests per minute exceeded"))
    sr.web_search("q1")
    sr.web_search("q2")
    assert c.calls == 2 and sr.pause_status() == ""


def test_429_credit_body_pauses(monkeypatch):
    c = _client(monkeypatch, FakeResp(429, text="You have exceeded your monthly API credits. Please upgrade your plan."))
    sr.web_search("q1")
    sr.web_search("q2")
    assert c.calls == 1 and "429" in sr.pause_status()


def test_429_unclear_body_does_not_pause(monkeypatch):
    c = _client(monkeypatch, FakeResp(429, text="error"))
    sr.web_search("q1")
    sr.web_search("q2")
    assert c.calls == 2


def test_timeout_and_network_errors_do_not_pause(monkeypatch):
    c = _client(monkeypatch, httpx.ReadTimeout("slow"), httpx.ConnectError("down"))
    assert sr.web_search("q1") == [] and sr.web_search("q2") == []
    sr.web_search("q3")
    assert c.calls == 3 and sr.pause_status() == ""


def test_pause_shows_in_trace_debug_without_key(monkeypatch):
    from odiro.agent import nodes

    _client(monkeypatch, FakeResp(432, text="usage limit"))
    sr.web_search("q")
    monkeypatch.setattr(nodes.summarize_reviews, "summarize_many", lambda places, cond: ["" for _ in places])
    monkeypatch.setattr(nodes, "_rag_review", lambda name, region: "")
    out = nodes.enrich({"request": {"region": "성수동"}, "places": [{"name": "가게A", "category": "카페"}], "trace": [], "rag_docs": []})
    step = out["trace"][-1]
    assert "Tavily 일시 중단(HTTP 432, 크레딧·한도 초과" in step["debug"] and "test-key" not in step["debug"]
    assert "Tavily" not in step["detail"]
