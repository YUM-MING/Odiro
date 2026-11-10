"""수집 스크립트 공통 유틸: JSONL 입출력, 재시도 HTTP, 일일 호출 한도 카운터, 진행 로그.

4개 스크립트(tour_api / naver_blog / labeling / build_index)가 전부 이 모듈만 쓴다.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from odiro.config import settings

log = logging.getLogger("odiro.ingest")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname).1s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # httpx 는 INFO 로 요청 URL 전체(serviceKey 포함!)를 찍으므로 반드시 끈다
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Windows 콘솔(cp949)에서 한글 깨짐 방지
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


# ---------- 경로 ----------

RAW_DIR: Path = settings.raw_data_dir
TOUR_DIR: Path = RAW_DIR / "tour"
BLOG_DIR: Path = RAW_DIR / "blog"
LABELED_DIR: Path = RAW_DIR / "labeled"
STATE_DIR: Path = settings.cache_dir / "ingest_state"


def ensure_dirs() -> None:
    for d in (TOUR_DIR, BLOG_DIR, LABELED_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ---------- JSONL ----------


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]], append: bool = False) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a" if append else "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_ids(path: Path, key: str) -> set[str]:
    """이미 저장된 행의 id 집합 (재실행 시 이어받기용)."""
    return {str(r[key]) for r in read_jsonl(path) if key in r}


# ---------- 일일 호출 한도 ----------


class DailyQuota:
    """API 별 오늘 호출 수를 파일에 기록해, 한도에 닿으면 멈추고 내일 이어서 돌릴 수 있게 한다.

    TourAPI 개발계정은 **기능별** 일 1,000건이라 name 에 기능명까지 넣는다 (예: "tour:detailCommon2").
    """

    def __init__(self, name: str, limit: int) -> None:
        self.name = name
        self.limit = limit
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.path = STATE_DIR / f"quota_{name.replace(':', '_').replace('/', '_')}.json"
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        today = date.today().isoformat()
        if self.path.exists():
            st = json.loads(self.path.read_text(encoding="utf-8"))
            if st.get("date") == today:
                return st
        return {"date": today, "used": 0}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._state), encoding="utf-8")

    @property
    def used(self) -> int:
        return int(self._state["used"])

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def exhausted(self) -> bool:
        return self.remaining <= 0

    def tick(self, n: int = 1) -> None:
        self._state["used"] = self.used + n
        self._save()

    def mark_exhausted(self) -> None:
        """서버가 한도 초과를 돌려줬을 때: 카운터가 어긋나 있어도 오늘은 더 호출하지 않게."""
        self._state["used"] = max(self.used, self.limit)
        self._save()


# ---------- HTTP ----------


class RetryableHTTPError(Exception):
    """5xx / 429 / 네트워크 오류처럼 재시도하면 될 수 있는 실패."""


class QuotaExceeded(Exception):
    """일일 한도 초과 (429 / data.go.kr LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR). 재시도하지 않고 내일."""


def _raise_for_retry(r: httpx.Response) -> None:
    if r.status_code == 429 or "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in r.text[:600]:
        raise QuotaExceeded(f"{r.status_code} 한도 초과: {r.text[:100]}")
    if r.status_code >= 500:
        raise RetryableHTTPError(f"{r.status_code} {r.text[:120]}")
    r.raise_for_status()


@retry(
    retry=retry_if_exception_type((RetryableHTTPError, httpx.TransportError)),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    stop=stop_after_attempt(5),
    reraise=True,
)
def get_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> Any:
    r = client.get(url, params=params, headers=headers, timeout=timeout)
    _raise_for_retry(r)
    try:
        return r.json()
    except ValueError as e:  # data.go.kr 은 오류를 XML 로 줄 때가 있다
        raise RetryableHTTPError(f"JSON 아님: {r.text[:160]}") from e


def polite_sleep(seconds: float) -> None:
    """공공 API 에 부담 안 주도록 호출 사이 짧게 쉰다."""
    if seconds > 0:
        time.sleep(seconds)
