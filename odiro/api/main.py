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
import queue
import threading
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from odiro import __version__
from odiro.api.schemas import (
    MOODS,
    CourseRequest,
    CourseResponse,
    EditRequest,
    JobStarted,
    TraceStep,
)
from odiro.config import settings

log = logging.getLogger("odiro.api")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Odiro API", version=__version__)
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
    return {"status": "ok", "version": __version__}


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


# ---------- 동기 ----------


def _run_course_blocking(req: CourseRequest) -> CourseResponse:
    from odiro.agent.run import run_course

    return run_course(req)


def _run_edit_blocking(edit: EditRequest) -> CourseResponse:
    from odiro.agent.run import run_edit

    return run_edit(edit)


@app.post("/api/course", response_model=CourseResponse)
async def create_course(req: CourseRequest) -> CourseResponse:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_run_course_blocking, req), timeout=SYNC_TIMEOUT_SEC)
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
        emit("progress", step.model_dump_json())

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
def start_course(req: CourseRequest) -> JobStarted:
    from odiro.agent.run import run_course

    return _start_job(run_course, req)


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
