"""Odiro FastAPI 진입점. 실행: uvicorn odiro.api.main:app --reload

- GET  /api/health, /api/config-check, /api/public-config, /api/moods
- POST /api/course                → 동기 생성 (CourseResponse)
- POST /api/course/start          → job_id (백그라운드 스레드에서 그래프 실행)
- GET  /api/course/stream/{job}   → SSE: progress* → result | error
- POST /api/course/edit           → 동기 수정
- POST /api/course/edit/start     → job_id
스키마는 odiro/api/schemas.py, 설명은 docs/API_SCHEMA.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from odiro import __version__
from odiro.api.schemas import (
    MOODS,
    CourseRequest,
    CourseResponse,
    DailyPick,
    EditRequest,
    JobStarted,
    TraceStep,
)
from odiro.config import settings

log = logging.getLogger("odiro.api")
logging.getLogger("httpx").setLevel(logging.WARNING)

# ---------- 시작 예열 (콜드스타트) ----------
# 첫 요청에서 그래프 모듈 import 와 벡터 DB(HNSW 색인 약 600MB) 첫 로딩이 겹쳐 retrieve 가 크게 늦어진다.
# Cloud Run 은 요청이 없을 때 CPU 를 거의 주지 않으므로, 예열은 서버가 포트를 열기 전(시작 단계, CPU 할당됨)에 한다.
# 최대 WARMUP_WAIT_SEC 까지만 기다리고, 넘거나 실패해도 서버는 그대로 뜬다 (못 끝낸 예열은 백그라운드에서 이어감).
# 외부 유료 API(OpenAI·Tavily·카카오)는 부르지 않는다. ODIRO_WARMUP=1 일 때만 (Dockerfile 에서 켬. 로컬·테스트는 꺼짐)
WARMUP_ENV = "ODIRO_WARMUP"
WARMUP_WAIT_SEC = 90
warmup_state: dict[str, Any] = {"status": "off", "ms": 0, "error": ""}


def _warmup() -> None:
    """그래프 모듈 import + 벡터 DB 열기·색인 로딩 + 이용 정보 표 읽기. 실패해도 예외를 밖으로 내지 않는다."""
    t0 = time.time()
    warmup_state.update(status="running", ms=0, error="")
    try:
        import odiro.agent.run  # noqa: F401  (LangGraph·LangChain·chromadb import)
        from odiro.tools import rag_search, tour_intro

        info = rag_search.warm()
        tour_intro._table()
        warmup_state.update(status="done", ms=int((time.time() - t0) * 1000))
        log.info("예열 완료 %.1fs %s", time.time() - t0, info)
    except Exception as e:  # noqa: BLE001  예열 실패는 첫 요청이 평소처럼 초기화하면 된다
        warmup_state.update(status="error", ms=int((time.time() - t0) * 1000), error=f"{type(e).__name__}: {str(e)[:120]}")
        log.warning("예열 실패 (요청 처리에는 영향 없음): %s", e)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if os.environ.get(WARMUP_ENV) == "1":
        th = threading.Thread(target=_warmup, name="warmup", daemon=True)
        th.start()
        await asyncio.to_thread(th.join, WARMUP_WAIT_SEC)  # 시작 단계에서 기다린다 (너무 길면 포기하고 서버를 연다)
        if th.is_alive():
            log.warning("예열이 %ss 안에 끝나지 않아 서버를 먼저 엽니다", WARMUP_WAIT_SEC)
    yield


app = FastAPI(title="Odiro API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOB_TTL_SEC = 600
SYNC_TIMEOUT_SEC = 90


# ---------- 기본 ----------


@app.get("/api/health")
def health() -> dict:
    # warmup: off(로컬) / running / done / error — 배포 뒤 콜드스타트 예열이 끝났는지 확인용 (기존 필드는 그대로)
    return {"status": "ok", "version": __version__, "warmup": warmup_state["status"]}


@app.get("/api/config-check")
def config_check() -> dict:
    """어떤 API 키가 비어 있는지 (값은 절대 노출하지 않음)."""
    missing = settings.missing_keys()
    return {"ready": not missing, "missing": missing}


@app.get("/api/public-config")
def public_config() -> dict:
    """프론트에 내려줘도 되는 설정 (Kakao JS 키는 도메인 제한으로 보호됨)."""
    return {"kakao_js_api_key": settings.kakao_js_api_key}


@app.get("/api/moods")
def moods() -> dict:
    return {"moods": list(MOODS)}


@app.get("/api/daily-pick", response_model=DailyPick)
def daily_pick(date: str | None = Query(None, description="YYYY-MM-DD. 생략하면 한국 시간 오늘")) -> DailyPick:
    """오늘의 숨은 여행지. data/tour_intro.json 의 후보에서 날짜마다 한 곳 (외부 API 호출 없음)."""
    from datetime import date as _date

    from odiro.tools import daily_pick as dp

    if date is None:
        day = dp.today_kst()
    else:
        try:
            day = _date.fromisoformat(date) if len(date) == 10 else None
        except ValueError:
            day = None
        if day is None:
            raise HTTPException(422, "date 는 YYYY-MM-DD 형식이어야 합니다")
    pick = dp.pick_for(day)
    if pick is None:
        raise HTTPException(404, "추천 후보가 없습니다")
    return DailyPick(**pick)


# ---------- 동기 ----------


def _run_course_blocking(req: CourseRequest, refresh: bool = False) -> CourseResponse:
    from odiro.agent.run import run_course

    return run_course(req, refresh=refresh)


def _run_edit_blocking(edit: EditRequest) -> CourseResponse:
    from odiro.agent.run import run_edit

    return run_edit(edit)


@app.post("/api/course", response_model=CourseResponse)
async def create_course(req: CourseRequest, refresh: bool = False) -> CourseResponse:
    """refresh=true 면 캐시를 건너뛰고 새로 만든다 (프론트의 '다시 만들기')."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_course_blocking, req, refresh), timeout=SYNC_TIMEOUT_SEC)
    except TimeoutError as e:
        raise HTTPException(503, "코스 생성이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.") from e
    except Exception as e:
        log.exception("course 실패")
        raise HTTPException(503, f"코스 생성 실패: {str(e)[:120]}") from e


@app.post("/api/course/edit", response_model=CourseResponse)
async def edit_course(edit: EditRequest) -> CourseResponse:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_edit_blocking, edit), timeout=SYNC_TIMEOUT_SEC)
    except TimeoutError as e:
        raise HTTPException(503, "수정이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.") from e
    except Exception as e:
        log.exception("edit 실패")
        raise HTTPException(503, f"수정 실패: {str(e)[:120]}") from e


# ---------- 비동기 + SSE ----------


@dataclass
class Job:
    id: str
    events: queue.Queue = field(default_factory=queue.Queue)
    done: bool = False
    created: float = field(default_factory=time.time)
    history: list[tuple[str, str]] = field(default_factory=list)  # 늦게 붙은 구독자용 (event, data)


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _gc_jobs() -> None:
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, job in _jobs.items() if now - job.created > JOB_TTL_SEC]:
            _jobs.pop(jid, None)


def _start_job(target, *args) -> JobStarted:
    _gc_jobs()
    job = Job(id=f"j_{uuid.uuid4().hex[:12]}")
    with _jobs_lock:
        _jobs[job.id] = job

    def emit(event: str, data: str) -> None:
        job.history.append((event, data))
        job.events.put((event, data))

    def on_progress(step: TraceStep) -> None:
        emit("progress", step.model_dump_json(exclude={"debug"}))  # 내부 판단 기록은 진행 이벤트로 보내지 않는다

    def worker() -> None:
        try:
            resp: CourseResponse = target(*args, on_progress)
            emit("result", resp.model_dump_json())
        except Exception as e:
            log.exception("job %s 실패", job.id)
            emit("error", json.dumps({"message": str(e)[:200]}, ensure_ascii=False))
        finally:
            job.done = True
            job.events.put(None)

    threading.Thread(target=worker, name=job.id, daemon=True).start()
    return JobStarted(job_id=job.id, stream_url=f"/api/course/stream/{job.id}")


@app.post("/api/course/start", response_model=JobStarted)
def start_course(req: CourseRequest, refresh: bool = False) -> JobStarted:
    """refresh=true 면 캐시를 건너뛰고 새로 만든다 (프론트의 '다시 만들기')."""
    from odiro.agent.run import run_course

    def target(r: CourseRequest, on_progress):
        return run_course(r, on_progress, refresh=refresh)

    return _start_job(target, req)


@app.post("/api/course/edit/start", response_model=JobStarted)
def start_edit(edit: EditRequest) -> JobStarted:
    from odiro.agent.run import run_edit

    return _start_job(run_edit, edit)


@app.get("/api/course/stream/{job_id}")
async def stream_course(job_id: str) -> EventSourceResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "없는 job_id (만료되었을 수 있음)")

    async def gen() -> AsyncIterator[dict[str, Any]]:
        # 이미 쌓인 이벤트부터 재생 (재접속 대비)
        sent = 0
        for ev, data in list(job.history):
            yield {"event": ev, "data": data}
            sent += 1
        if job.done and sent == len(job.history):
            return
        # 큐에서 새 이벤트. history 재생분은 건너뛴다
        skipped = 0
        while True:
            try:
                item = await asyncio.to_thread(job.events.get, True, 15)
            except queue.Empty:
                yield {"comment": "keep-alive"}
                continue
            if item is None:
                return
            if skipped < sent:
                skipped += 1
                continue
            ev, data = item
            yield {"event": ev, "data": data}
            if ev in ("result", "error"):
                return

    return EventSourceResponse(gen(), ping=15)
