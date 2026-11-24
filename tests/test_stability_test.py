"""scripts/stability_test.py — 모의 HTTP 서버로만 시험한다 (배포·로컬 앱 서버, 외부 API 호출 없음). 결과 파일은 임시 디렉터리."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import stability_test as st

TRACE = [{"node": "parse_intent", "status": "done", "ms": 1200, "detail": ""},
         {"node": "retrieve", "status": "done", "ms": 3400, "detail": ""},
         {"node": "enrich", "status": "skip", "ms": None, "detail": ""}]
SECRET_PLACE = "비밀장소이름"  # 응답 본문이 결과 파일에 들어가지 않는지 확인용


def _course(places: int = 3, warnings: int = 0, cached: bool = False) -> dict:
    return {"places": [{"name": f"{SECRET_PLACE}{i}"} for i in range(places)], "answer": "본문",
            "meta": {"warnings": [f"경고{i}" for i in range(warnings)], "web_docs": 7, "cached": cached, "trace": TRACE}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # 응답이 끝나면 연결을 닫는다 → 스트림 끝

    def log_message(self, *a):  # 조용히
        pass

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(200, {"status": "ok", "version": "0.3.0", "warmup": "done"})
        scenario = self.server.scenario  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(event: str, data) -> None:
            payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
            self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
            self.wfile.flush()

        try:
            if scenario == "before_first":
                return
            self.wfile.write(b": keep-alive\n\n")
            for t in TRACE[:2]:
                send("progress", {"node": t["node"], "status": "start", "ms": None, "detail": ""})
                send("progress", t)
            if scenario == "endless":
                while True:
                    send("progress", {"node": "enrich", "status": "start", "ms": None, "detail": ""})
                    time.sleep(0.05)
            if scenario == "slow":
                time.sleep(0.4)
            if scenario in ("ok", "slow"):
                send("result", _course())
            elif scenario == "warn":
                send("result", _course(warnings=2, cached=True))
            elif scenario == "empty":
                send("result", _course(places=0))
            elif scenario == "bad":
                send("result", "not json")
            elif scenario == "sse_error":
                send("error", {"message": "내부 오류 원문 OPENAI_API_KEY=sk-xxx"})
            # no_result: 진행 이벤트 뒤 그냥 끝
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        scenario = self.server.scenario  # type: ignore[attr-defined]
        if scenario == "start500":
            return self._json(500, {"detail": "boom"})
        if scenario == "start429":
            return self._json(429, {"detail": "slow down"})
        return self._json(200, {"job_id": "j1", "stream_url": "/api/course/stream/j1"})


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    srv.scenario = "ok"  # type: ignore[attr-defined]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield srv, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _once(base: str, stream_timeout: float = 5.0) -> st.Run:
    with httpx.Client() as c:
        return st.run_once(c, base, st._item(st.PRESETS[0], "2026-11-28"), 1, time.monotonic(), stream_timeout=stream_timeout)


@pytest.mark.parametrize(("scenario", "expected"), [
    ("ok", "success"), ("warn", "success"), ("start500", "http_5xx"), ("start429", "http_429"), ("sse_error", "sse_error"),
    ("no_result", "stream_ended_no_result"), ("before_first", "stream_before_first"), ("empty", "empty_course"), ("bad", "bad_response"),
])
def test_classification(server, scenario, expected):
    srv, base = server
    srv.scenario = scenario
    r = _once(base)
    assert r.result == expected
    assert r.elapsed_s is not None and r.elapsed_s >= 0
    if scenario in ("start500", "start429"):
        assert r.http_status in (500, 429) and r.first_event_s is None
    if scenario in ("ok", "warn"):
        assert r.http_status == 200 and r.places == 3 and r.web_docs == 7 and r.first_event_s is not None
        assert r.warnings == (2 if scenario == "warn" else 0) and r.cached is (scenario == "warn")
        assert r.phase_source == "meta.trace" and r.phases_ms == {"parse_intent": 1200, "retrieve": 3400, "enrich": None}
    if scenario == "no_result":
        assert r.phase_source == "progress" and r.phases_ms == {"parse_intent": 1200, "retrieve": 3400}


def test_events_past_total_limit_is_client_timeout(server):
    srv, base = server
    srv.scenario = "endless"  # 진행 이벤트가 계속 와도 전체 상한이 지나면 끊는다 (사이트의 150초와 같은 방식)
    t = time.monotonic()
    r = _once(base, stream_timeout=0.6)
    assert r.result == "client_timeout" and r.first_event_s is not None
    assert time.monotonic() - t < 5


def test_connection_failure_is_network_error():
    with socket.socket() as s:  # 비어 있는 포트
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert _once(f"http://127.0.0.1:{port}").result == "network_error"


def test_request_body_matches_frontend_presets():
    src = (ROOT / "frontend" / "src" / "request.ts").read_text(encoding="utf-8")
    for p in st.PRESETS:
        assert f"label: '{p['label']}'" in src and f"region: '{p['patch']['region']}'" in src
    assert "start_time: '11:00'" in src and "end_time: '20:00'" in src and "budget: 100_000" in src
    assert "STREAM_TOTAL_TIMEOUT_MS = 150_000" in (ROOT / "frontend" / "src" / "api.ts").read_text(encoding="utf-8")
    gp = st.build_request(st.PRESETS[1], "2026-11-28")
    assert gp["days"] == 2 and gp["mode"] == "trip" and gp["date"] == "2026-11-28" and gp["free_text"] == "" and gp["lodging"] == ""
    sb = st.build_request(st.PRESETS[3], "2026-11-28")
    assert sb["days"] == 1 and sb["party"] == "" and "day_starts" not in sb
    assert st.next_saturday(__import__("datetime").date(2026, 11, 24)) == "2026-11-28"
    assert st.next_saturday(__import__("datetime").date(2026, 11, 28)) == "2026-11-28"
    assert [it["preset"]["label"] for it in st.plan_of(st.parse_args(["--runs", "20"]))].count("가평 1박 2일") == 4


def test_sequential_measure_saves_sanitized_file(server, tmp_path):
    srv, base = server
    srv.scenario = "sse_error"
    args = st.parse_args(["--runs", "2", "--base-url", base, "--gap", "0"])
    path = st.measure(args, out_dir=tmp_path, sleep=lambda s: None)
    assert path.parent == tmp_path and path.name.endswith("_seq2.json")
    text = path.read_text(encoding="utf-8")
    assert "sk-xxx" not in text and "내부 오류" not in text  # 오류 원문을 저장하지 않는다
    d = json.loads(text)
    assert d["health_before"]["body"] == {"status": "ok", "version": "0.3.0", "warmup": "done"} and d["health_after"]["body"]["status"] == "ok"
    assert d["health_before"]["revision"] == "미확인"
    assert [r["result"] for r in d["runs"]] == ["sse_error", "sse_error"]
    s = d["summary"]
    assert s["attempted"] == 2 and s["success"] == 0 and s["success_rate"] == 0.0 and s["success_time_s"]["n"] == 0
    assert len(s["failure_elapsed_s"]) == 2 and s["by_class"] == {"sse_error": 2}

    srv.scenario = "ok"
    path = st.measure(st.parse_args(["--runs", "3", "--base-url", base, "--gap", "0", "--no-health"]), out_dir=tmp_path, sleep=lambda s: None)
    text = path.read_text(encoding="utf-8")
    assert SECRET_PLACE not in text and "경고" not in text  # 응답 본문을 저장하지 않는다
    d = json.loads(text)
    assert d["health_before"] is None and d["meta"]["requests"] == 3
    s = d["summary"]
    assert s["success"] == 3 and s["success_rate"] == 1.0 and s["fresh_success_time_s"]["n"] == 3
    assert s["phases"]["parse_intent"] == {"n": 3, "mean_ms": 1200, "no_record": 0}
    assert s["phases"]["enrich"] == {"n": 0, "mean_ms": None, "no_record": 3}  # ms 가 없으면 0 이 아니라 '기록 없음'
    report = st.render_report([path])
    assert "| 3 | 3 | 1.0 |" in report and "| enrich | 0 | - | 3 |" in report


def test_concurrent_measure_overlaps(server, tmp_path):
    srv, base = server
    srv.scenario = "slow"
    path = st.measure(st.parse_args(["--concurrent", "3", "--base-url", base, "--no-health"]), out_dir=tmp_path)
    d = json.loads(path.read_text(encoding="utf-8"))
    assert path.name.endswith("_concurrent3.json") and len(d["runs"]) == 3
    assert {r["result"] for r in d["runs"]} == {"success"}
    c = d["concurrency"]
    assert c["start_spread_s"] < 0.3 and c["all_overlap_s"] > 0.2  # 같은 순간 시작, 서버에서 함께 진행
    assert "동시 시작 차이" in st.render_report([path])


def test_summary_stats_and_percentile():
    assert st.percentile([], 0.9) is None
    assert st.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 9  # nearest-rank: ceil(0.9×10)=9 번째
    assert st.percentile([5.0], 0.9) == 5.0
    runs = [
        {"result": "success", "elapsed_s": 30.0, "cached": False, "first_event_s": 1.0, "phases_ms": {"a": 100}},
        {"result": "success", "elapsed_s": 45.0, "cached": False, "first_event_s": 2.0, "phases_ms": {"a": None}},
        {"result": "success", "elapsed_s": 2.0, "cached": True, "first_event_s": 0.5, "phases_ms": {}},
        {"result": "client_timeout", "elapsed_s": 150.0},
        {"result": "http_5xx", "elapsed_s": 0.2},
    ]
    s = st.summarize_runs(runs)
    assert s["attempted"] == 5 and s["success"] == 3 and s["success_rate"] == 0.6
    assert s["success_over_target"] == 1 and s["timeout_failures"] == 1 and s["cached_success"] == 1
    assert s["fresh_success_time_s"]["n"] == 2 and s["fresh_success_time_s"]["max"] == 45.0
    assert s["failure_elapsed_s"] == [150.0, 0.2]
    assert s["phases"]["a"] == {"n": 1, "mean_ms": 100, "no_record": 2}
    assert st.concurrency_info([{"start_offset_s": 0.0, "end_offset_s": 10.0}, {"start_offset_s": 0.1, "end_offset_s": 3.0}]) == {
        "start_spread_s": 0.1, "all_overlap_s": 2.9}


def test_report_mode_reads_only_files(tmp_path, capsys, monkeypatch):
    f = tmp_path / "x_seq1.json"
    f.write_text(json.dumps({"meta": {"mode": "seq1"}, "runs": [{"result": "success", "elapsed_s": 10.0, "cached": False}]}), encoding="utf-8")
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("요청 금지")))
    st.main(["--report", str(f)])
    out = capsys.readouterr().out
    assert "x_seq1.json" in out and "| 1 | 1 | 1.0 |" in out


def test_dry_run_makes_no_request(capsys, monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("요청 금지")))
    st.main(["--runs", "20", "--dry-run", "--date", "2026-11-28"])
    out = capsys.readouterr().out
    assert "요청 20건" in out and "2026-11-28" in out and st.DEFAULT_BASE_URL in out


# ---------- 실행 계획: 서버 결과 캐시에 걸리지 않게 ----------

TODAY = __import__("datetime").date(2026, 11, 24)
AVOID = "gapyeong:2026-11-28,seongsu:2026-11-28"


def _plans(avoid: str = AVOID):
    dates = st.forecast_dates(TODAY)
    return st.slot_plans(dates, st.parse_avoid(avoid), dates[-1])


def test_forecast_dates_inside_weather_range():
    # get_weather.weather(): 오늘 ~ +5일만 예보. 서버 UTC·OpenWeather 120시간 여유로 +1~+4일
    assert st.forecast_dates(TODAY) == ["2026-11-25", "2026-11-26", "2026-11-27", "2026-11-28"]


def test_default_plans_unique_and_disjoint_across_modes():
    plans = _plans()
    assert {k: len(v) for k, v in plans.items()} == {"idle": 1, "seq": 20, "c3": 3, "c5": 5, "custom": 0}
    combos = [it["combo"] for v in plans.values() for it in v]
    assert len(combos) == 29 and len(set(combos)) == 29  # 계획 안에서도, 네 측정 사이에서도 같은 조합 없음
    assert len({json.dumps(it["request"], sort_keys=True) for v in plans.values() for it in v}) == 29  # 요청 본문(=캐시 키) 기준으로도
    for slot in ("seq", "c3", "c5"):
        assert not {it["combo"] for it in plans[slot]} & {it["combo"] for s, v in plans.items() if s != slot for it in v}
    seq_labels = [it["preset"]["key"] for it in plans["seq"]]
    assert all(seq_labels.count(p["key"]) == 4 for p in st.PRESETS)
    assert sorted(it["preset"]["key"] for it in plans["c5"]) == sorted(p["key"] for p in st.PRESETS)
    assert all(it["date"] in st.forecast_dates(TODAY) for v in plans.values() for it in v)
    assert not any(c.startswith(("seongsu:2026-11-28:", "gapyeong:2026-11-28:")) for c in combos)  # --avoid
    # 바꾸는 값은 사이트에서 고를 수 있는 것만: 시작 시각(10:00/11:00), 교통수단(walk/car). 나머지는 프리셋 그대로
    for it in (it for v in plans.values() for it in v):
        base = st.build_request(it["preset"], it["date"])
        diff = {k for k in base if base[k] != it["request"][k]}
        assert diff <= {"start_time", "transport"} and len(diff) <= 1
        assert it["request"]["start_time"] in ("10:00", "11:00") and it["request"]["transport"] in ("walk", "car")


def test_trip_end_date_inside_forecast_range():
    last = st.forecast_dates(TODAY)[-1]
    trips = [it for v in _plans().values() for it in v if it["request"]["mode"] == "trip"]
    assert trips
    for it in trips:
        end = __import__("datetime").date.fromisoformat(it["date"]) + __import__("datetime").timedelta(days=it["request"]["days"] - 1)
        assert end.isoformat() <= last  # 1박 2일 종료일까지 예보 범위 안


def test_plan_of_slots_and_date_backcompat(monkeypatch):
    plans = _plans()
    for argv, slot in ((["--runs", "1"], "idle"), (["--runs", "20"], "seq"), (["--concurrent", "3"], "c3"), (["--concurrent", "5"], "c5")):
        args = st.parse_args([*argv, "--avoid", AVOID])
        assert st.slot_of(args) == slot
        assert [it["combo"] for it in st.plan_of(args, today=TODAY)] == [it["combo"] for it in plans[slot]]
    # --date 하나: 예전처럼 모든 요청이 그 날짜·기본 조건 (프리셋 돌아가며)
    old = st.plan_of(st.parse_args(["--runs", "6", "--date", "2026-11-28"]), today=TODAY)
    assert [it["date"] for it in old] == ["2026-11-28"] * 6
    assert [it["preset"]["key"] for it in old] == ["seongsu", "gapyeong", "songdo", "bukchon", "suwon", "seongsu"]
    assert old[0]["request"] == st.build_request(st.PRESETS[0], "2026-11-28")
    # custom: 표준 29건 뒤에서 꺼내 표준 슬롯과 겹치지 않는다
    custom = st.plan_of(st.parse_args(["--runs", "4", "--avoid", AVOID]), today=TODAY)
    assert not {it["combo"] for it in custom} & {it["combo"] for v in plans.values() for it in v}


def test_dates_option_and_limits():
    with pytest.raises(ValueError, match="예보 범위"):
        st.plan_of(st.parse_args(["--runs", "20", "--dates", "2026-11-25,2026-12-10"]), today=TODAY)
    with pytest.raises(ValueError, match="모자란다"):  # 날짜 하나로는 29건을 못 만든다 (캐시 강제 삭제 대신 멈춘다)
        st.plan_of(st.parse_args(["--runs", "20", "--dates", "2026-11-25"]), today=TODAY)
    two = st.plan_of(st.parse_args(["--concurrent", "3", "--dates", "2026-11-26,2026-11-27"]), today=TODAY)
    assert {it["date"] for it in two} <= {"2026-11-26", "2026-11-27"}


def test_avoid_excludes_combos():
    assert st.parse_avoid(" gapyeong:2026-11-28 , seongsu:2026-11-27:walk:11:00 ") == ["gapyeong:2026-11-28", "seongsu:2026-11-27:walk:11:00"]
    with pytest.raises(ValueError, match="프리셋 이름"):
        st.parse_avoid("busan:2026-11-28")
    pool = st.universe(st.forecast_dates(TODAY), st.parse_avoid("seongsu:2026-11-27:walk:11:00,bukchon:2026-11-26"), None)
    seongsu = {it["combo"] for it in pool["seongsu"]}
    assert "seongsu:2026-11-27:walk:11:00" not in seongsu and "seongsu:2026-11-27:walk:10:00" in seongsu  # 정확한 조합만
    assert not any(it["date"] == "2026-11-26" for it in pool["bukchon"])  # 날짜까지만 주면 그 날짜 변형 모두
    assert len(pool["bukchon"]) == 9 and len(pool["songdo"]) == 12


def test_check_against_stops_on_overlap(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(httpx.Client, "send", lambda *a, **k: (_ for _ in ()).throw(AssertionError("요청 금지")))
    plan = st.plan_of(st.parse_args(["--concurrent", "3", "--avoid", AVOID]))
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps({"meta": {}, "runs": [{"preset": plan[1]["preset"]["label"], "combo": plan[1]["combo"]}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="겹치는 조합"):
        st.main(["--concurrent", "3", "--avoid", AVOID, "--dry-run", "--check-against", str(prev)])
    other = tmp_path / "other.json"  # 다른 슬롯(연속 20)의 결과와는 겹치지 않는다
    seq = st.plan_of(st.parse_args(["--runs", "20", "--avoid", AVOID]))
    other.write_text(json.dumps({"meta": {}, "runs": [{"combo": it["combo"]} for it in seq]}), encoding="utf-8")
    st.main(["--concurrent", "3", "--avoid", AVOID, "--dry-run", "--check-against", str(other)])
    assert "겹치는 조합 없음" in capsys.readouterr().out
    # combo 가 없는 옛 파일은 프리셋·meta.date·기본 조건으로 복원
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"meta": {"date": "2026-11-28"}, "runs": [{"preset": "가평 1박 2일"}]}), encoding="utf-8")
    assert st.used_combos([old]) == {"gapyeong:2026-11-28:car:11:00"}


def test_cached_runs_warning_and_fresh_success_rate(tmp_path):
    runs = [
        {"result": "success", "elapsed_s": 2.0, "cached": True, "combo": "a"},
        {"result": "success", "elapsed_s": 30.0, "cached": False, "combo": "b"},
        {"result": "success", "elapsed_s": 50.0, "cached": False, "combo": "c"},
        {"result": "sse_error", "elapsed_s": 20.0, "combo": "d"},
    ]
    s = st.summarize_runs(runs)
    assert s["cached_runs"] == 1 and s["fresh_attempted"] == 3 and s["fresh_success"] == 2 and s["fresh_success_rate"] == 0.667
    assert s["success_rate"] == 0.75  # 전체 요청 기준
    assert s["fresh_success_time_s"]["n"] == 2 and s["fresh_success_time_s"]["mean"] == 40.0
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"meta": {"mode": "seq4"}, "runs": runs, "summary": s}), encoding="utf-8")
    report = st.render_report([f]).splitlines()
    assert report[2].startswith("**캐시 적중 1회**") and "⚠" in report[2]  # 요약 맨 위
    assert any("신규 생성 성공률(캐시 아닌 요청 기준) 0.667 (2/3)" in line and "전체 요청 성공률 0.75 (3/4)" in line for line in report)
    s0 = st.summarize_runs([r for r in runs if not r.get("cached")])
    f.write_text(json.dumps({"meta": {}, "runs": [], "summary": s0}), encoding="utf-8")
    assert "⚠" not in st.render_report([f]).splitlines()[2]


def test_run_records_date_and_combo(server):
    srv, base = server
    srv.scenario = "warn"
    r = _once(base)
    assert r.date == "2026-11-28" and r.combo == "seongsu:2026-11-28:walk:11:00" and r.cached is True
