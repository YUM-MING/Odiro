"""Day 3 안정화 측정: 배포(또는 로컬) 서버에 사이트와 같은 순서로 코스 생성을 요청하고 결과를 분류·기록한다.

⚠ 실제 코스를 만든다 → OpenAI·Tavily·카카오 등 외부 API 비용이 든다. 사용자가 직접 실행한다.
⚠ 운영 기준: daily-ingest(매일 06:30 KST)·main 푸시 배포가 끝난 뒤 측정하고, 측정 전후로 GitHub Actions 에
   배포 실행이 없었는지 직접 확인한다. 측정 도중 배포가 있었으면 그 결과는 같은 조건의 측정으로 보지 않는다.

요청 순서 (frontend/src/api.ts · Plan.tsx 와 같다)
  1. POST {base}/api/course/start  본문 = CourseRequest (defaultRequest() 위에 프리셋을 applyPreset 으로 덮은 값)
     → 200 {job_id, stream_url}. axios 기본 타임아웃 60초 (api.ts `axios.create({ timeout: 60_000 })`)
  2. GET {base}{stream_url}  SSE. 이벤트 progress(TraceStep JSON) * → result(CourseResponse JSON) | error({"message"})
     keep-alive 는 SSE 주석(':')이라 이벤트가 아니다.
     전체 상한 150초 = STREAM_TOTAL_TIMEOUT_MS. 스트림을 연 순간부터 잰다 (이벤트가 계속 와도 150초가 지나면 끊는다).
  ※ 사이트는 스트림이 첫 이벤트 전에 끊기면 동기 API(POST /api/course, 100초)로 한 번 더 요청한다.
     이 스크립트는 그 대체 요청을 하지 않는다(자동 재시도 금지) — 'stream_before_first' 로 분류만 한다.
  ※ 사이트는 첫 생성에 refresh 를 붙이지 않는다 → 같은 요청이면 서버의 7일 결과 캐시가 쓰인다. 캐시를 끄거나 지우지 않고,
     실행 계획을 서로 다른 요청(프리셋 × 예보 범위 날짜, 모자라면 시작 시각 10:00 → 교통수단 바꿈)으로 만든다.
     네 측정(유휴 후 첫 요청·연속 20·동시 3·동시 5)은 고정 슬롯으로 나눠 서로 같은 조합을 쓰지 않는다.
     그래도 이전 요청과 겹치면 캐시가 쓰일 수 있어 meta.cached 를 기록하고, 신규 생성 성공률·시간을 따로 본다.

성공 = result 이벤트를 받았고, JSON 이 CourseResponse 모양이며, places 가 비어 있지 않음. 경고가 있어도 성공(경고 수 기록).

사용 예 (네 측정에 같은 --avoid 를 준다. 날짜는 실행한 날 기준 +1~+4일이라 같은 날 모두 돌린다)
  A="gapyeong:2026-11-28,seongsu:2026-11-28"
  python scripts/stability_test.py --runs 1 --no-health --label idle-first --avoid $A        # 유휴 후 첫 요청 (슬롯 idle)
  python scripts/stability_test.py --runs 20 --avoid $A --check-against cache/stability/*.json   # 연속 20 (슬롯 seq)
  python scripts/stability_test.py --concurrent 3 --avoid $A --check-against cache/stability/*.json
  python scripts/stability_test.py --concurrent 5 --avoid $A --check-against cache/stability/*.json
  python scripts/stability_test.py --runs 20 --avoid $A --dry-run   # 요청 없이 계획(조합)만 출력
  python scripts/stability_test.py --runs 5 --date 2026-11-28      # 예전 방식: 날짜 하나 (반복하면 캐시에 걸린다)
  python scripts/stability_test.py --report cache/stability/*.json   # 저장된 결과만 읽어 표로 (서버 요청 없음)
결과: cache/stability/<YYYYMMDD-HHMMSS>_<모드>.json  (응답 본문·오류 원문·키는 저장하지 않는다. 상태 코드와 분류만)
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import math
import queue
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "cache" / "stability"

# deploy.yml 의 frontend 빌드 기본값 (VITE_API_URL). 다르면 --base-url 로
DEFAULT_BASE_URL = "https://odiro-api-80160454962.asia-northeast3.run.app"
START_TIMEOUT_S = 60.0  # api.ts: axios.create({ timeout: 60_000 })
STREAM_TOTAL_TIMEOUT_S = 150.0  # api.ts: STREAM_TOTAL_TIMEOUT_MS
TARGET_S = 40.0  # 응답 시간 목표 (HANDOVER: 40초 이하)
SYNC_LIMIT_S = 100.0  # api.ts: SYNC_REQUEST_TIMEOUT_MS (동기 대체 요청의 상한) — 참고용 집계

# 결과 분류
SUCCESS = "success"
CLASSES = (
    SUCCESS, "sse_error", "stream_before_first", "stream_ended_no_result", "bad_response", "empty_course",
    "http_429", "http_5xx", "http_other", "network_error", "client_timeout",
)


# frontend/src/request.ts 의 defaultRequest() 와 PRESETS (date 는 실행 때 넣는다). 바뀌면 테스트가 알려 준다
DEFAULT_REQUEST: dict[str, Any] = {
    "mode": "outing", "transport": "walk", "region": "", "start_time": "11:00", "end_time": "20:00", "days": 1,
    "budget": 100_000, "moods": [], "free_text": "", "party": "", "headcount": 1, "lodging": "",
}
PRESETS: list[dict[str, Any]] = [
    {"key": "seongsu", "label": "성수동 데이트", "patch": {"region": "성수동", "mode": "outing", "transport": "walk", "moods": ["감성/조용한", "사진맛집"], "party": "연인"}},
    {"key": "gapyeong", "label": "가평 1박 2일", "patch": {"region": "가평", "mode": "trip", "transport": "car", "days": 2, "moods": ["자연/산책", "뷰맛집/일몰"], "party": "연인"}},
    {"key": "songdo", "label": "인천 송도 아이와", "patch": {"region": "인천 송도", "mode": "outing", "transport": "car", "moods": ["아이동반", "실내(비오는날)"], "party": "가족(아이 1)"}},
    {"key": "bukchon", "label": "북촌 한옥 산책", "patch": {"region": "북촌", "mode": "outing", "transport": "walk", "moods": ["레트로", "자연/산책", "사진맛집"]}},
    {"key": "suwon", "label": "수원 화성 레트로", "patch": {"region": "수원 화성", "mode": "outing", "transport": "walk", "moods": ["레트로", "사진맛집"]}},
]
PRESET_BY_KEY = {p["key"]: p for p in PRESETS}

# ---------- 실행 계획: 서버 결과 캐시에 걸리지 않게 서로 다른 요청으로 ----------
# 서버 결과 캐시 키 = cache_key("course", req.model_dump()) (odiro/agent/run.py) → 요청 필드 전부. 이 스크립트가 바꾸는 값은
# 날짜·교통수단·시작 시각뿐이라 (프리셋, 날짜, 교통수단, 시작 시각) 이 같으면 같은 캐시 키다.
# 날씨 예보 범위: get_weather.weather() 는 서버의 date.today() ~ +5일만 받는다. 서버(Cloud Run)는 UTC 라 KST 00~09시에는
# 서버 '오늘'이 하루 전이고, OpenWeather 5일 예보(3시간 × 40칸)는 +5일 낮 시간대를 일부만 덮는다 → 여유 있게 +1~+4일.
# 오늘은 빼다: 측정 시각이 출발 11:00 을 지나 있을 수 있다.
FORECAST_FIRST, FORECAST_LAST = 1, 4
# 날짜만으로 모자라면 사이트에서 고를 수 있는 값만 바꾼다 (Builder.tsx: 시작 시각 30분 단위 입력, 뚜벅이/자차 선택).
# 프리셋 성격을 덜 바꾸는 시작 시각을 먼저, 그다음 교통수단.
VARIANTS = ("base", "start10", "alt_transport")
# 측정 모드별 고정 슬롯: 계획 전체(29건)를 이 순서로 한 번에 나눠, 네 측정이 서로 같은 조합을 쓰지 않게 한다.
SLOTS: dict[str, list[str]] = {
    "idle": ["suwon"],
    "seq": [p["key"] for _ in range(4) for p in PRESETS],  # 프리셋 5개 × 4회, 돌아가며
    "c3": ["seongsu", "songdo", "bukchon"],
    "c5": [p["key"] for p in PRESETS],
}


def next_day(today: date | None = None) -> str:
    """request.ts nextDay(): 사이트의 기본 출발일 = 다음 날(내일). (측정 계획은 이 값이 아니라 forecast_dates 를 쓴다)"""
    d = today or date.today()
    return (d + timedelta(days=1)).isoformat()


def forecast_dates(today: date | None = None) -> list[str]:
    d = today or date.today()
    return [(d + timedelta(days=i)).isoformat() for i in range(FORECAST_FIRST, FORECAST_LAST + 1)]


def build_request(preset: dict[str, Any], day: str, variant: str = "base") -> dict[str, Any]:
    """request.ts applyPreset(defaultRequest(), preset) 와 같은 본문 (+ 사이트에서 고를 수 있는 값 하나만 바꾼 변형).
    Plan.tsx generate() 가 빼는 day_starts 는 원래 없다."""
    req = {**DEFAULT_REQUEST, "date": day, "free_text": "", "lodging": "", "party": "", **preset["patch"]}
    if req["mode"] == "outing":
        req["days"] = 1
        req["lodging"] = ""
    if variant == "start10":
        req["start_time"] = "10:00"
    elif variant == "alt_transport":
        req["transport"] = "car" if req["transport"] == "walk" else "walk"
    return req


def combo_of(preset: dict[str, Any], req: dict[str, Any]) -> str:
    """캐시 키를 가르는 값만 모은 표시. 예) seongsu:2026-11-28:walk:11:00"""
    return f"{preset['key']}:{req['date']}:{req['transport']}:{req['start_time']}"


def _item(preset: dict[str, Any], day: str, variant: str = "base") -> dict[str, Any]:
    req = build_request(preset, day, variant)
    return {"preset": preset, "date": day, "variant": variant, "request": req, "combo": combo_of(preset, req)}


def parse_avoid(text: str) -> list[str]:
    """'gapyeong:2026-11-28,seongsu:2026-11-28' → 접두어 목록. 날짜까지만 주면 그 날짜의 모든 변형을 뺀다 (안전한 쪽)."""
    out = []
    for raw in (text or "").split(","):
        s = raw.strip()
        if not s:
            continue
        key = s.split(":", 1)[0]
        if key not in PRESET_BY_KEY:
            raise ValueError(f"--avoid 의 프리셋 이름을 모른다: {key} (가능: {', '.join(PRESET_BY_KEY)})")
        out.append(s)
    return out


def _avoided(combo: str, avoid: list[str]) -> bool:
    return any(combo == a or combo.startswith(a + ":") for a in avoid)


def universe(dates: list[str], avoid: list[str], last_day: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """프리셋별로 쓸 수 있는 고유 요청 (변형 순서 → 날짜 순서). 여행은 종료일까지 last_day 안이어야 한다."""
    out: dict[str, list[dict[str, Any]]] = {}
    for p in PRESETS:
        items = []
        for v in VARIANTS:
            for d in dates:
                end = (date.fromisoformat(d) + timedelta(days=int(p["patch"].get("days", 1)) - 1)).isoformat()
                if last_day and end > last_day:
                    continue
                it = _item(p, d, v)
                if not _avoided(it["combo"], avoid):
                    items.append(it)
        out[p["key"]] = items
    return out


def slot_plans(dates: list[str], avoid: list[str], last_day: str | None, extra: int = 0) -> dict[str, list[dict[str, Any]]]:
    """네 측정 모드(+ 그 밖 'custom' extra 건)의 계획을 한 번에 나눈다. 모자라면 ValueError."""
    pools = {k: list(v) for k, v in universe(dates, avoid, last_day).items()}
    plans: dict[str, list[dict[str, Any]]] = {}
    for slot, keys in [*SLOTS.items(), ("custom", [PRESETS[i % len(PRESETS)]["key"] for i in range(extra)])]:
        plan = []
        for k in keys:
            if not pools[k]:
                raise ValueError(f"고유 조합이 모자란다: {slot} 슬롯의 {PRESET_BY_KEY[k]['label']} (날짜 {', '.join(dates)})")
            plan.append(pools[k].pop(0))
        plans[slot] = plan
    return plans


def slot_of(args: argparse.Namespace) -> str:
    if args.slot != "auto":
        return args.slot
    n = args.concurrent or args.runs
    if args.concurrent:
        return {3: "c3", 5: "c5"}.get(n, "custom")
    return {1: "idle", 20: "seq"}.get(n, "custom")


def plan_of(args: argparse.Namespace, today: date | None = None) -> list[dict[str, Any]]:
    """--date 하나면 예전처럼 그 날짜·기본 조건으로 프리셋을 돌아가며 (하위 호환, 반복하면 캐시에 걸린다).
    아니면 예보 범위 날짜(또는 --dates)로 측정 모드별 고정 슬롯을 나눠 서로 다른 요청만 쓴다."""
    n = args.concurrent or args.runs
    if args.date:
        return [_item(PRESETS[i % len(PRESETS)], args.date) for i in range(n)]
    allowed = forecast_dates(today)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()] if args.dates else allowed
    outside = [d for d in dates if d not in allowed]
    if outside:
        raise ValueError(f"날씨 예보 범위({allowed[0]}~{allowed[-1]}) 밖 날짜: {', '.join(outside)}")
    slot = slot_of(args)
    plans = slot_plans(dates, parse_avoid(args.avoid), allowed[-1], extra=n if slot == "custom" else 0)
    plan = plans[slot]
    if len(plan) != n:
        raise ValueError(f"{slot} 슬롯은 {len(plan)}건이다 (요청 {n}건). --slot custom 을 쓰거나 회수를 맞춘다")
    return plan


def used_combos(files: list[Path]) -> set[str]:
    """이전 측정 결과 파일들에서 쓴 조합. combo 가 없는 옛 파일은 프리셋·meta.date·기본 조건으로 복원."""
    by_label = {p["label"]: p for p in PRESETS}
    out: set[str] = set()
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for r in d.get("runs", []):
            if r.get("combo"):
                out.add(r["combo"])
            elif r.get("preset") in by_label and (r.get("date") or d.get("meta", {}).get("date")):
                p = by_label[r["preset"]]
                out.add(combo_of(p, build_request(p, r.get("date") or d["meta"]["date"])))
    return out


@dataclass
class Run:
    index: int
    preset: str
    date: str  # 출발일
    combo: str  # 캐시 키를 가르는 값: 프리셋:날짜:교통수단:시작시각
    started_at: str  # 실제 시작 시각 (로컬 ISO)
    start_offset_s: float  # 측정 시작 기준 실제 요청 시작 (monotonic)
    end_offset_s: float = 0.0
    result: str = ""
    http_status: int | None = None  # 시작 요청의 상태 코드 (스트림에서 실패하면 스트림 상태 코드)
    elapsed_s: float | None = None  # 시작 요청 ~ 결과/실패 (monotonic)
    first_event_s: float | None = None  # 시작 요청 ~ 첫 진행 이벤트
    places: int | None = None
    warnings: int | None = None
    web_docs: int | None = None  # 응답 meta.web_docs = 웹 검색 '결과' 건수 (외부 API 호출 횟수·크레딧 아님)
    cached: bool | None = None  # 응답 meta.cached (서버 7일 결과 캐시)
    phases_ms: dict[str, int | None] = field(default_factory=dict)  # 노드별 ms. 모르면 그 노드는 없음(null 취급)
    phase_source: str | None = None  # "meta.trace" | "progress" | None


def _phases_from_trace(trace: Any) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for t in trace if isinstance(trace, list) else []:
        if isinstance(t, dict) and t.get("node") and t.get("status") in ("done", "skip", "error"):
            ms = t.get("ms")
            out[str(t["node"])] = int(ms) if isinstance(ms, int | float) else None
    return out


def _sse_events(lines_q: queue.Queue, deadline: float):
    """줄 큐 → (event, data) 이벤트. 마감(monotonic)이 지나면 ('__timeout__', None). 스트림이 끝나면 멈춘다."""
    event, data = "message", []
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            yield "__timeout__", None
            return
        try:
            item = lines_q.get(timeout=min(left, 1.0))
        except queue.Empty:
            continue
        if item is None:  # 스트림 끝
            return
        if isinstance(item, Exception):
            raise item
        line = item.rstrip("\r")
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "message", []
        elif line.startswith(":"):
            continue  # keep-alive 주석
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))


def run_once(
    client: httpx.Client, base_url: str, item: dict[str, Any], index: int, t0: float,
    start_timeout: float = START_TIMEOUT_S, stream_timeout: float = STREAM_TOTAL_TIMEOUT_S, barrier: threading.Barrier | None = None,
) -> Run:
    """코스 1회. 예외를 밖으로 내지 않고 분류해 돌려준다. 자동 재시도 없음."""
    if barrier is not None:
        barrier.wait()  # 동시 모드: N개가 같은 순간에 시작
    start = time.monotonic()
    run = Run(index=index, preset=item["preset"]["label"], date=item["date"], combo=item["combo"], started_at=datetime.now().isoformat(timespec="milliseconds"), start_offset_s=round(start - t0, 3))

    def finish(result: str) -> Run:
        now = time.monotonic()
        run.result = result
        run.elapsed_s = round(now - start, 3)
        run.end_offset_s = round(now - t0, 3)
        return run

    try:
        r = client.post(f"{base_url}/api/course/start", json=item["request"], timeout=start_timeout)
    except httpx.TimeoutException:
        return finish("client_timeout")
    except httpx.HTTPError:
        return finish("network_error")
    run.http_status = r.status_code
    if r.status_code != 200:
        return finish(_http_class(r.status_code))
    try:
        stream_url = r.json()["stream_url"]
    except (ValueError, KeyError, TypeError):
        return finish("bad_response")

    deadline = time.monotonic() + stream_timeout  # 사이트와 같이 스트림을 연 순간부터 전체 상한
    lines_q: queue.Queue = queue.Queue()
    holder: dict[str, Any] = {}

    def reader() -> None:
        try:
            with client.stream("GET", f"{base_url}{stream_url}", timeout=httpx.Timeout(10.0, read=stream_timeout + 5)) as resp:
                holder["resp"] = resp
                holder["status"] = resp.status_code
                if resp.status_code != 200:
                    lines_q.put(None)
                    return
                for line in resp.iter_lines():
                    lines_q.put(line)
                    if holder.get("stop"):
                        return
        except Exception as e:  # noqa: BLE001  분류는 받는 쪽에서
            lines_q.put(e)
            return
        lines_q.put(None)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    got_progress = False
    trace_from_progress: dict[str, int | None] = {}
    try:
        for ev, data in _sse_events(lines_q, deadline):
            if ev == "__timeout__":
                return finish("client_timeout")
            if ev == "progress":
                if not got_progress:
                    run.first_event_s = round(time.monotonic() - start, 3)
                got_progress = True
                try:
                    step = json.loads(data)
                    if isinstance(step, dict) and step.get("status") in ("done", "skip", "error") and step.get("node"):
                        ms = step.get("ms")
                        trace_from_progress[str(step["node"])] = int(ms) if isinstance(ms, int | float) else None
                except ValueError:
                    pass
            elif ev == "result":
                return finish(_classify_result(run, data, trace_from_progress))
            elif ev == "error":
                return finish("sse_error")  # 메시지 원문은 저장하지 않는다
    except httpx.TimeoutException:
        return finish("client_timeout")
    except Exception:  # noqa: BLE001  연결 끊김 등
        return finish("stream_ended_no_result" if got_progress else "network_error")
    finally:
        holder["stop"] = True
        resp = holder.get("resp")
        if resp is not None:
            with contextlib.suppress(Exception):
                resp.close()
    if holder.get("status") not in (None, 200):
        run.http_status = holder["status"]
        return finish(_http_class(holder["status"]))
    if trace_from_progress:
        run.phases_ms, run.phase_source = trace_from_progress, "progress"
    return finish("stream_ended_no_result" if got_progress else "stream_before_first")


def _http_class(status: int) -> str:
    if status == 429:
        return "http_429"
    if 500 <= status < 600:
        return "http_5xx"
    return "http_other"


def _classify_result(run: Run, data: str, trace_from_progress: dict[str, int | None]) -> str:
    try:
        course = json.loads(data)
        places, meta = course["places"], course.get("meta") or {}
        if not isinstance(places, list):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return "bad_response"
    run.places = len(places)
    run.warnings = len(meta.get("warnings") or [])
    run.web_docs = meta.get("web_docs") if isinstance(meta.get("web_docs"), int) else None
    run.cached = bool(meta.get("cached")) if "cached" in meta else None
    phases = _phases_from_trace(meta.get("trace"))
    if phases:
        run.phases_ms, run.phase_source = phases, "meta.trace"
    elif trace_from_progress:
        run.phases_ms, run.phase_source = trace_from_progress, "progress"
    return SUCCESS if places else "empty_course"


def get_health(client: httpx.Client, base_url: str) -> dict[str, Any]:
    """/api/health 응답 전체(작은 JSON: status·version·warmup). 배포 리비전은 응답에 없어 '미확인'."""
    try:
        r = client.get(f"{base_url}/api/health", timeout=60)
        body = r.json() if r.status_code == 200 else None
        return {"at": datetime.now().isoformat(timespec="seconds"), "http_status": r.status_code, "body": body, "revision": "미확인"}
    except Exception as e:  # noqa: BLE001
        return {"at": datetime.now().isoformat(timespec="seconds"), "error": type(e).__name__, "revision": "미확인"}


# ---------- 요약 ----------


def percentile(values: list[float], p: float) -> float | None:
    """가장 가까운 순위(nearest-rank) 방식: 정렬한 값의 ceil(p×n) 번째. 표본이 없으면 None."""
    if not values:
        return None
    s = sorted(values)
    return s[max(1, math.ceil(p * len(s))) - 1]


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """성공률 분모 = 시도한 전체 회수. 시간 통계는 성공만(캐시 아닌 성공은 따로), 실패는 경과 시간 목록만."""
    n = len(runs)
    ok = [r for r in runs if r["result"] == SUCCESS]
    fresh = [r for r in ok if r.get("cached") is False]
    cached_runs = sum(1 for r in runs if r.get("cached") is True)
    fresh_attempted = n - cached_runs  # 결과 캐시에서 나온 회차를 뺀 요청 (실패는 새로 만들다 실패한 것으로 본다)
    fresh_ok = [r for r in ok if r.get("cached") is not True]
    times = [r["elapsed_s"] for r in ok if r.get("elapsed_s") is not None]
    fresh_times = [r["elapsed_s"] for r in fresh if r.get("elapsed_s") is not None]

    def stats(xs: list[float]) -> dict[str, Any]:
        return {"n": len(xs), "mean": round(sum(xs) / len(xs), 1) if xs else None, "p50": percentile(xs, 0.5), "p90": percentile(xs, 0.9), "max": max(xs) if xs else None}

    phases: dict[str, dict[str, Any]] = {}
    for r in ok:
        for node, ms in (r.get("phases_ms") or {}).items():
            phases.setdefault(node, {"values": [], "missing": 0})
            if ms is None:
                phases[node]["missing"] += 1
            else:
                phases[node]["values"].append(ms)
    phase_stats = {
        node: {"n": len(v["values"]), "mean_ms": round(sum(v["values"]) / len(v["values"])) if v["values"] else None,
               "no_record": len(ok) - len(v["values"])}
        for node, v in phases.items()
    }
    first = [r["first_event_s"] for r in ok if r.get("first_event_s") is not None]
    by_class = {c: sum(1 for r in runs if r["result"] == c) for c in CLASSES}
    return {
        "attempted": n,
        "cached_runs": cached_runs,  # meta.cached = true 회차 (요약 맨 위에 표시)
        "fresh_attempted": fresh_attempted,
        "fresh_success": len(fresh_ok),
        "fresh_success_rate": round(len(fresh_ok) / fresh_attempted, 3) if fresh_attempted else None,  # 신규 생성 성공률
        "success": len(ok),
        "success_rate": round(len(ok) / n, 3) if n else None,  # 전체 요청 성공률 (분모 = 시도 회수)
        "by_class": {k: v for k, v in by_class.items() if v},
        "success_time_s": stats(times),
        "fresh_success_time_s": stats(fresh_times),  # 캐시 아닌 성공 (실제 생성 시간)
        "cached_success": sum(1 for r in ok if r.get("cached")),
        "cached_unknown": sum(1 for r in ok if r.get("cached") is None),
        "success_over_target": sum(1 for x in times if x > TARGET_S),
        "success_over_100s": sum(1 for x in times if x > SYNC_LIMIT_S),
        "timeout_failures": by_class.get("client_timeout", 0),
        "failure_elapsed_s": [r["elapsed_s"] for r in runs if r["result"] != SUCCESS],
        "first_event_s": stats(first),
        "phases": phase_stats,
        "warnings_total": sum(r.get("warnings") or 0 for r in ok),
        "web_docs_mean": round(sum(w) / len(w), 1) if (w := [r["web_docs"] for r in ok if r.get("web_docs") is not None]) else None,
    }


def concurrency_info(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """동시 모드: 실제 시작 시각 차이(최대-최소)와 모두가 함께 진행 중이던 구간."""
    if not runs:
        return {}
    starts = [r["start_offset_s"] for r in runs]
    ends = [r["end_offset_s"] for r in runs]
    overlap = min(ends) - max(starts)
    return {"start_spread_s": round(max(starts) - min(starts), 3), "all_overlap_s": round(max(0.0, overlap), 3)}


def render_report(files: list[Path]) -> str:
    """저장된 측정 JSON 만 읽어 리포트용 마크다운 표 (서버 요청 없음)."""
    out = []
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        s, m = d.get("summary") or summarize_runs(d.get("runs", [])), d.get("meta", {})
        st, fr = s.get("success_time_s", {}), s.get("fresh_success_time_s", {})
        hb, ha = d.get("health_before") or {}, d.get("health_after") or {}

        def fmt(x: Any) -> str:
            return "-" if x is None else str(x)

        cached_runs = s.get("cached_runs", s.get("cached_success", 0))
        combos = [r.get("combo") or f"{r.get('preset')}:{r.get('date') or m.get('date')}" for r in d.get("runs", [])]
        out += [
            f"### {f.name}",
            "",
            f"**캐시 적중 {cached_runs}회** / 시도 {s['attempted']}회"
            + (" — ⚠ 서버 결과 캐시에서 나온 회차가 있다. 신규 생성 성공률·시간은 캐시 아닌 요청으로 본다" if cached_runs else ""),
            "",
            (f"- 신규 생성 성공률(캐시 아닌 요청 기준) {fmt(s.get('fresh_success_rate'))} ({s.get('fresh_success', '-')}/{s.get('fresh_attempted', '-')})"
             f" · 전체 요청 성공률 {fmt(s['success_rate'])} ({s['success']}/{s['attempted']})"),
            f"- 조합: {', '.join(c for c in combos if c) or '-'}",
            f"- 모드 {m.get('mode')} · 슬롯 {m.get('slot', '-')} · 대상 {m.get('base_url')} · 날짜 {', '.join(m.get('dates') or [m.get('date') or '-'])} · 커밋 {m.get('commit', '미확인')} · 시작 {m.get('started_at')}",
            f"- health 전: {json.dumps(hb.get('body') or hb.get('error'), ensure_ascii=False)} / 후: {json.dumps(ha.get('body') or ha.get('error'), ensure_ascii=False)} (리비전 미확인)",
            "",
            "| 시도 | 성공 | 성공률 | 캐시 성공 | 40초 초과 성공 | 100초 초과 성공 | 시간 초과 실패 | 실패 분류 |",
            "|---|---|---|---|---|---|---|---|",
            (f"| {s['attempted']} | {s['success']} | {fmt(s['success_rate'])} | {s.get('cached_success')} | {s.get('success_over_target')} | "
             f"{s.get('success_over_100s')} | {s.get('timeout_failures')} | {', '.join(f'{k} {v}' for k, v in s['by_class'].items() if k != SUCCESS) or '-'} |"),
            "",
            "| 구분 | 표본 | 평균(초) | p50 | p90 | 최대 |",
            "|---|---|---|---|---|---|",
            f"| 성공 전체 | {st.get('n')} | {fmt(st.get('mean'))} | {fmt(st.get('p50'))} | {fmt(st.get('p90'))} | {fmt(st.get('max'))} |",
            f"| 캐시 아닌 성공 | {fr.get('n')} | {fmt(fr.get('mean'))} | {fmt(fr.get('p50'))} | {fmt(fr.get('p90'))} | {fmt(fr.get('max'))} |",
            f"| 첫 진행 이벤트 | {s['first_event_s'].get('n')} | {fmt(s['first_event_s'].get('mean'))} | {fmt(s['first_event_s'].get('p50'))} | {fmt(s['first_event_s'].get('p90'))} | {fmt(s['first_event_s'].get('max'))} |",
            "",
            "| 단계 | 기록 있는 성공 | 평균(ms) | 기록 없음 |",
            "|---|---|---|---|",
            *[f"| {node} | {v['n']} | {fmt(v['mean_ms'])} | {v['no_record']} |" for node, v in s["phases"].items()],
        ]
        if d.get("concurrency"):
            c = d["concurrency"]
            out += ["", f"- 동시 시작 차이 {c.get('start_spread_s')}초, 모두 함께 진행된 구간 {c.get('all_overlap_s')}초"]
        out.append("")
    return "\n".join(out)


# ---------- 실행 ----------


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=False, cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() or "미확인"
    except Exception:  # noqa: BLE001
        return "미확인"


def measure(
    args: argparse.Namespace, client: httpx.Client | None = None, out_dir: Path | None = None, sleep=time.sleep,
    plan: list[dict[str, Any]] | None = None,
) -> Path:
    base = args.base_url.rstrip("/")
    plan = plan if plan is not None else plan_of(args)
    mode = f"concurrent{args.concurrent}" if args.concurrent else f"seq{args.runs}"
    label = f"{mode}_{args.label}" if args.label else mode
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": "odiro-stability-test"})
    meta = {
        "mode": mode, "label": args.label or "", "base_url": base, "date": args.date or "", "dates": sorted({it["date"] for it in plan}),
        "slot": "date" if args.date else slot_of(args), "avoid": args.avoid, "commit": git_commit(),
        "started_at": datetime.now().isoformat(timespec="seconds"), "requests": len(plan),
        "combos": [it["combo"] for it in plan], "gap_s": args.gap, "stream_timeout_s": args.timeout, "start_timeout_s": START_TIMEOUT_S,
        "deploy_settings_declared": "deploy.yml: --min-instances 0 --max-instances 1 --memory 4Gi --cpu 1 --timeout 120 (실제 배포 설정은 미확인)",
        "note": "측정 모드별로 서로 다른 (프리셋, 날짜, 교통수단, 시작 시각) 을 쓴다. 그래도 이전 요청과 같으면 서버 결과 캐시가 쓰일 수 있다 (meta.cached 로 구분). 측정 전후 배포가 없었는지 사용자 확인 필요.",
    }
    try:
        health_before = None if args.no_health else get_health(client, base)
        t0 = time.monotonic()
        runs: list[Run] = []
        if args.concurrent:
            barrier = threading.Barrier(args.concurrent)
            results: list[Run | None] = [None] * len(plan)

            def worker(i: int) -> None:
                results[i] = run_once(client, base, plan[i], i + 1, t0, stream_timeout=args.timeout, barrier=barrier)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(plan))]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
            runs = [r for r in results if r is not None]
        else:
            for i, p in enumerate(plan):
                if i:
                    sleep(args.gap)
                r = run_once(client, base, p, i + 1, t0, stream_timeout=args.timeout)
                runs.append(r)
                print(f"[{i + 1}/{len(plan)}] {p['combo']}: {r.result} {r.elapsed_s}s" + (" (캐시)" if r.cached else ""), flush=True)
        health_after = None if args.no_health else get_health(client, base)
    finally:
        if own:
            client.close()
    rows = [asdict(r) for r in runs]
    data = {"meta": meta, "health_before": health_before, "health_after": health_after, "runs": rows, "summary": summarize_runs(rows)}
    if args.concurrent:
        data["concurrency"] = concurrency_info(rows)
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{label}.json"
    i = 2
    while path.exists():
        path = out_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{label}-{i}.json"
        i += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--runs", type=int, default=20, help="연속 모드 회수 (기본 20: 프리셋 5개 × 4회)")
    g.add_argument("--concurrent", type=int, help="동시 모드: 같은 순간에 N개 시작 (3·5 는 따로 실행)")
    g.add_argument("--report", nargs="+", metavar="FILE", help="저장된 측정 JSON 만 읽어 표로 출력 (서버 요청 없음)")
    ap.add_argument("--date", default="", help="출발일 하나만 (예전 방식: 모든 요청이 그 날짜·기본 조건. 반복하면 서버 결과 캐시에 걸린다)")
    ap.add_argument("--dates", default="", help="쓸 날짜들 (쉼표 구분). 기본: 오늘 기준 +1~+4일 (날씨 예보 범위 안)")
    ap.add_argument("--slot", default="auto", choices=["auto", "idle", "seq", "c3", "c5", "custom"],
                    help="측정 모드별 고정 슬롯 (auto: --runs 1→idle, --runs 20→seq, --concurrent 3→c3, 5→c5, 그 밖→custom)")
    ap.add_argument("--avoid", default="", help="이미 쓴 조합 제외, 예) gapyeong:2026-11-28,seongsu:2026-11-28 (날짜까지면 그 날짜 변형 모두). 네 측정에 똑같이 준다")
    ap.add_argument("--check-against", nargs="+", metavar="FILE", help="이전 측정 결과 파일과 조합이 겹치면 실행 전에 멈춘다")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--gap", type=float, default=5.0, help="연속 모드 요청 간격(초)")
    ap.add_argument("--timeout", type=float, default=STREAM_TOTAL_TIMEOUT_S, help="스트림 전체 상한(초, 사이트와 같이 150)")
    ap.add_argument("--no-health", action="store_true", help="측정 전후 /api/health 요청을 하지 않는다 (콜드스타트를 강제하는 옵션은 아님)")
    ap.add_argument("--label", default="", help="파일 이름에 붙일 표시 (예: idle-first)")
    ap.add_argument("--dry-run", action="store_true", help="요청하지 않고 계획만 출력")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    if args.report:
        files = sorted({Path(h) for pat in args.report for h in (glob.glob(pat) or [pat]) if Path(h).exists()})
        if not files:
            sys.exit(f"측정 파일을 찾지 못했다: {args.report}")
        print(render_report(files))
        return
    try:
        plan = plan_of(args)
    except ValueError as e:
        sys.exit(f"실행 계획을 만들 수 없다: {e}")
    mode = f"동시 {args.concurrent}개" if args.concurrent else f"연속 {args.runs}회 (간격 {args.gap}초)"
    where = f"날짜 {args.date} (하나, 반복은 캐시에 걸린다)" if args.date else f"슬롯 {slot_of(args)} · 날짜 {', '.join(sorted({it['date'] for it in plan}))}"
    print(f"대상 {args.base_url} · {where} · 모드 {mode} · 코스 생성 요청 {len(plan)}건 (외부 API 비용 발생)")
    print("조합:", ", ".join(it["combo"] for it in plan))
    if len({it["combo"] for it in plan}) < len(plan):
        print("⚠ 이 계획 안에 같은 조합이 있다 → 2회차부터 서버 결과 캐시에 걸린다")
    if args.check_against:
        files = sorted({Path(h) for pat in args.check_against for h in (glob.glob(pat) or [pat]) if Path(h).exists()})
        dup = sorted({it["combo"] for it in plan} & used_combos(files))
        if dup:
            sys.exit(f"이전 측정({len(files)}개 파일)과 겹치는 조합이 있어 멈춘다: {', '.join(dup)}")
        print(f"이전 측정 {len(files)}개 파일과 겹치는 조합 없음")
    print("⚠ daily-ingest·푸시 배포가 끝난 뒤인지, 측정 중 배포가 없었는지 GitHub Actions 에서 확인하세요.")
    if args.dry_run:
        return
    path = measure(args, plan=plan)
    d = json.loads(path.read_text(encoding="utf-8"))
    print("\n" + render_report([path]))
    print(f"저장: {path}")
    if d["summary"]["attempted"] and d["summary"]["success"] < d["summary"]["attempted"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
