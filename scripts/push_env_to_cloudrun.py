"""로컬 .env 의 API 키를 Cloud Run `odiro-api` 환경변수로 올린다 (값은 화면에 출력하지 않음).

실행 (gcloud 로그인 + 프로젝트 설정된 상태에서):
    python scripts/push_env_to_cloudrun.py            # 적용
    python scripts/push_env_to_cloudrun.py --dry-run  # 어떤 키가 올라갈지만 출력

동작: .env → 임시 YAML → `gcloud run services update odiro-api --env-vars-file` → 임시 파일 삭제.
Cloud Run 은 환경변수가 바뀌면 새 리비전을 만들어 자동 배포한다 (코드는 그대로).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICE, REGION, PROJECT = "odiro-api", "asia-northeast3", "odiro-where"
KEYS = [
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "EMBEDDING_MODEL",
    "KAKAO_REST_API_KEY", "KAKAO_JS_API_KEY", "KAKAO_MOBILITY_API_KEY", "TMAP_APP_KEY",
    "TOUR_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "TAVILY_API_KEY", "OPENWEATHER_API_KEY", "KMA_API_KEY",
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m and m.group(1) in KEYS:
            v = m.group(2).strip().strip('"').strip("'")
            if v:
                env[m.group(1)] = v
    if "TOUR_API_KEY" in env and "%" in env["TOUR_API_KEY"]:
        sys.exit("TOUR_API_KEY 가 Encoding 키로 보입니다. .env 에 Decoding 키를 넣으세요.")
    return env


def find_gcloud() -> str:
    for cand in ("gcloud", "gcloud.cmd", str(Path.home() / "google-cloud-sdk" / "bin" / "gcloud.cmd")):
        path = shutil.which(cand) or (cand if Path(cand).exists() else None)
        if path:
            return path
    sys.exit("gcloud 를 찾을 수 없습니다. 설치 후 `gcloud auth login` 을 먼저 하세요.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    print(f"올릴 변수 {len(env)}개: {', '.join(sorted(env))}")
    if args.dry_run:
        return
    gcloud = find_gcloud()
    fd, tmp = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("".join(f"{k}: {json.dumps(v)}\n" for k, v in env.items()))
        cmd = [gcloud, "run", "services", "update", SERVICE, "--region", REGION, "--project", PROJECT,
               "--env-vars-file", tmp, "--quiet"]
        print("실행:", " ".join(cmd[:6]), "...")
        r = subprocess.run(cmd, check=False)
        if r.returncode != 0:
            sys.exit(f"gcloud 실패 (exit {r.returncode})")
    finally:
        Path(tmp).unlink(missing_ok=True)
    print("완료. 확인: curl https://odiro-where.web.app/api/config-check  → ready: true 여야 함")


if __name__ == "__main__":
    main()
