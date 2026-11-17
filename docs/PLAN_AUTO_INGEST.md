# 일일 자동 수집·배포 계획 (GitHub Actions)

작성일 2026-11-17. **B(변경·삭제 갱신)와 C(워크플로)는 코드로 구현했다 (로컬 테스트 통과, 아직 커밋·push 전). Actions 에서는 한 번도 돌려 보지 않았다.** 남은 것은 D(버킷 초기 업로드와 실행 검증)와 A(권한 확인)다. "확인됨"은 코드·문서로 확인한 것, "미확인"은 아직 모르는 것이다.

## 1. 왜 하는가

한국관광공사 TourAPI 운영계정 신청서에 아래를 약속했다. 신청서대로 동작해야 한다.

- 로컬 DB 저장 방식 허가 신청. 일 10,000건 증량.
- 동기화: GitHub Actions 로 **매일 06:30(KST) 자동 실행, 1일 1회**.
- 관광공사 데이터가 매일 04:30 에 갱신되므로 06:00 이후에 동기화해야 전날 데이터를 받지 않는다.
- 동기화 책임은 전적으로 신청자에게 있다. **변경·삭제 갱신이 꼭 있어야 한다.**

## 2. 현재 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| 이용 정보(detailIntro2) 수집·표시 | 구현·push 완료 | `scripts/daily_ingest.py`, `build_intro_lookup.py`, `odiro/tools/tour_intro.py`, `MapView.tsx` |
| 출처 표기 "출처 : ⓒ한국관광공사" | 구현·push 완료 (배포 결과는 미확인) | 푸터, 일정 화면, 장소 카드, 지도 정보 창 |
| 일일 자동 수집 워크플로 | **작성함, 미실행** (커밋 전) | `.github/workflows/daily-ingest.yml`, `deploy.yml` 에 `workflow_call`·`tour_intro.json` 다운로드 추가 |
| 변경·삭제 갱신 | **구현·로컬 테스트 통과** (커밋 전, 실제 API 미호출) | `odiro/data/ingest/sync.py`, `tour_api.py`, `scripts/daily_ingest.py`, `tests/test_ingest_sync.py`, `tests/test_daily_ingest_flow.py` |
| 배포용 벡터 DB | GCS `gs://odiro-where-data/vectorstore.tgz` | 로컬 최신판(약 595MB, 인천·경기 포함)을 사용자가 업로드했다고 함. 업로드 후 재배포는 미확인 |
| GitHub Secrets (`TOUR_API_KEY`, `TOUR_API_KEYS_EXTRA`, `OPENAI_API_KEY`) | 팀원이 등록했다고 함, **이름 미확인** | 저장소 Settings → Secrets 에서 확인 |
| 서비스 계정(`GCP_SA_KEY`)의 버킷 쓰기 권한 | **미확인** | 배포는 읽기만 했다 |

기술 사실 (확인됨)
- API 키는 `odiro/config.py` 가 `.env` 와 환경변수를 모두 읽는다. Actions 는 Secrets 를 `env:` 로 넘기면 되고 `.env` 가 필요 없다.
- 배포(`deploy.yml`)는 main push 또는 수동 실행에만 반응한다. 벡터 DB 는 GCS 에서 받아 이미지에 넣는다.
- `.dockerignore` 가 `data/raw/*`, `cache/*` 를 제외한다. 서버는 raw 를 읽지 않는다. 서버가 쓰는 것은 벡터 DB 와 `data/tour_intro.json` 이다.
- `data/tour_intro.json` 은 **git 에 들어 있다.** 배포 이미지는 이 git 판을 쓴다.
- 이 PC 에는 `gcloud`, `gh` 가 없다.

## 3. 해야 할 일

### A. 권한·설정 확인 (사용자 작업, 먼저)
1. 저장소 Secrets 에 `TOUR_API_KEY`, `TOUR_API_KEYS_EXTRA`, `OPENAI_API_KEY` 가 있는지, 이름이 정확한지 확인.
2. 프로젝트 소유자에게 `GCP_SA_KEY` 서비스 계정이 `odiro-where-data` 버킷에 **쓰기**(`Storage Object Admin` 등) 권한이 있는지 확인.
3. GitHub Variable `CI_ENABLED` 가 `"true"` 인지 확인 (아니면 배포 job 이 건너뛰어진다).
4. 사용자 계정은 버킷 단위 권한만 있다. 버킷 직접 주소로 접속한다:
   `https://console.cloud.google.com/storage/browser/odiro-where-data?project=odiro-where`

### B. 변경·삭제 갱신 구현 — **구현 완료 (실제 API 로는 미검증)**
구현 결과 요약
- 판정은 날짜가 아니라 장소별 `modified` 비교다. 수집 날짜는 저장하지 않는다. `modified` 가 없던 옛 기록에는 그때 받은 목록의 값을 채워 기준으로 쓴다.
- 변경: detail·intro 에 `modified` 를 기록하고, 목록의 값과 다르면 다시 받는다. 새 상세가 도착할 때만 옛 라벨·벡터를 지우고(purge 큐) 다시 만든다. 그 전까지는 옛 정보를 서비스한다.
- 삭제: detail·intro 즉시 삭제, 라벨·벡터는 purge 큐로 지운다. `tour_intro.json` 은 매번 다시 만든다.
- 안전장치: 삭제가 저장 건수의 5%(최소 30건)를 넘거나 새 목록이 비면 중단하고 종료 코드 1 (`--force-removal` 로 허용).
- 하루 한 번만 목록을 다시 받는다 (`cache/ingest_state/synced_*.json`).

확인된 사실: 목록 API 는 `modifiedtime` 을 준다. 전체 목록 갱신은 약 50~110회 호출 (`areaBasedList2`, 기록상 110회). 상세·이용 정보 한도가 병목이고, 한도 단위(엔드포인트별/합산)는 **여전히 미확인**.

원래 계획 (참고)
1. ~~목록 API 가 `modifiedtime` 을 주는지, 호출 한도 확인~~ → 위 확인 결과 참조.
2. 시도별 목록(`area_*.jsonl`)의 `modifiedtime` 을 저장해 두고, 새 목록과 비교한다.
3. 바뀐 건: 상세·이용 정보를 다시 받고, 라벨링·임베딩을 다시 한다.
4. 목록에서 사라진 건: `detail_*`, `intro_*`, 라벨, **벡터 인덱스(Chroma)**, `tour_intro.json` 에서 모두 삭제한다.
5. 테스트를 쓴다. 삭제 로직은 잘못되면 데이터를 잃으므로 필수다. 삭제 전 개수 점검(예: 한 번에 전체의 N% 이상 사라지면 중단)도 넣는다.
6. 이용 정보는 **원문 그대로** 저장·표시한다. AI 가 고쳐 쓴 값을 관광공사 출처로 내지 않는다 (원문 훼손 금지).

### C. 워크플로 작성 — **작성 완료 (Actions 에서 미실행)**
1. `deploy.yml` 에 `workflow_call` 을 추가한다 (수집 워크플로가 호출할 수 있게).
2. `.github/workflows/daily-ingest.yml` 추가.
   - 트리거: `schedule: cron "30 21 * * *"` (UTC 21:30 = 한국 06:30), `workflow_dispatch` (수동 버튼).
   - 순서: 체크아웃 → 파이썬 설치 → `pip install -e .` → GCP 로그인 → 버킷에서 데이터 받기 → `daily_ingest.py` 실행 → 결과 업로드 → deploy 호출.
   - `concurrency` 로 동시에 두 번 돌지 않게 한다.
   - 수집이 실패하면 업로드·배포를 하지 않는다 (깨진 데이터가 올라가는 것을 막는다).
3. 버킷에 올리고 받을 대상
   - `data/raw/` (원본·라벨), `cache/ingest_state/` (수집 상태), `vectorstore.tgz`, `tour_intro.json`.
4. `tour_intro.json` 은 매일 새로 만들어지므로 반영 방식을 정해야 한다. 안 정하면 이용 정보가 갱신되지 않는다.
   - **권장: 버킷에 올리고 deploy 가 받아서 이미지에 넣는다.** (git 커밋 충돌이 없다.) `deploy.yml` 에 다운로드 단계를 추가하고, git 의 판은 초기값으로만 둔다.
   - 대안: Actions 가 git 에 커밋 push. 구현은 쉽지만 매일 커밋이 쌓이고 push 가 또 배포를 일으킨다.
5. 승인되어 한도가 오르면 명령어에 `--daily-limit 10000` 을 추가한다. 승인 전에는 넣지 않는다. (`daily-ingest.yml` 의 Ingest 단계 주석 위치)
6. 구현 메모: 버킷에 `ingest-data.tgz`(= `data/raw` + `cache/ingest_state`), `vectorstore.tgz`, `tour_intro.json` 세 개를 둔다. 올릴 때 이전 판은 `backup/` 에 한 세대 남긴다. 버킷에 `ingest-data.tgz` 가 없으면 처음부터 시작하지 않고 실패한다.

### D. 최초 설정과 검증
1. 사용자가 현재 로컬의 `data/raw`, `cache/ingest_state`, `tour_intro.json` 을 버킷에 올린다 (Actions 가 이어서 받을 출발점).
2. Actions 탭에서 `daily-ingest` 를 **수동으로 한 번** 돌린다. 첫 실행은 실패할 가능성이 높다 (권한, 경로, 의존성). 2~3회 반복을 예상한다.
3. 확인 항목
   - 버킷의 파일 갱신 시각이 바뀌었는가.
   - 배포가 호출되고 성공했는가.
   - 사이트에서 인천·경기 코스가 나오고 이용 정보에 "출처 : ⓒ한국관광공사" 가 보이는가.
   - Cloud Run 로그에 `Memory limit` 경고가 없는가 (인덱스가 커져 4Gi 가 부족할 수 있음).
4. cron 은 **기본 브랜치(main)의 워크플로만** 실행된다. main 에 올린 뒤 다음 날 06:30 직후 실제로 돌았는지 확인한다. GitHub 의 예약 실행은 몇 분~수십 분 늦을 수 있으므로 06:00 이전으로 당겨지지는 않지만 약간 늦을 수 있다.

## 4. 운영 규칙
- Actions 로 옮긴 뒤에는 **각자 PC 에서 수집을 돌리지 않는다.** 데이터가 갈라진다. 보려면 버킷에서 받는다.
- 인수인계용 `odiro-data-*.tgz`, `vectorstore-*.tgz` 는 더 이상 필요 없다. 버킷이 기준이다.
- 팀원 권한은 버킷 단위로 부여된다. 버킷 목록 화면은 열리지 않는 것이 정상이다. `gcloud` 는 `gs://odiro-where-data/` 경로를 직접 지정한다.

## 5. 비용
- Actions: 공개 저장소면 무료, 비공개면 무료 한도 안에서 거의 무료 (한도는 미확인).
- OpenAI 라벨링·임베딩: 3,000건 약 300~500원, 10,000건 약 1,000~1,700원 (추정, 실제 청구액은 대시보드에서 확인).
- GCS 저장·전송: 하루 수백 MB 업·다운로드. 소액이지만 실제 청구는 미확인.

## 6. 순서와 시간 추정

| 순서 | 작업 | 담당 | 추정 |
|---|---|---|---|
| 1 | A. 권한·Secrets 확인 | 사용자 | 20~30분 |
| 2 | B-1. 목록 API `modifiedtime`·호출 한도 확인 | 나 | ✅ 완료 (한도 단위만 미확인) |
| 3 | B-2~6. 변경·삭제 갱신 구현·테스트 | 나 | ✅ 완료 (미커밋) |
| 4 | C. 워크플로·`deploy.yml` 수정 | 나 | ✅ 작성 완료 (미실행) |
| 5 | D-1. 초기 데이터 버킷 업로드 | 사용자 | 20~30분 |
| 6 | D-2~3. 수동 실행·검증 (반복 포함) | 둘 다 | 1~3시간 |
| 7 | D-4. main 반영 후 다음 날 cron 확인 | 사용자 | 5분 |

순수 작업은 6~9시간, 확인 대기와 반복 실행을 넣으면 1~2일. 심사는 5~7일 이상 걸린다고 하니 그 안에 끝낼 수 있다.

## 7. 아직 모르는 것 (구현 전에 확인)
- 서비스 계정의 버킷 쓰기 권한.
- Secrets 의 정확한 이름.
- `data/` 와 `cache/ingest_state` 의 현재 크기 (업·다운로드 시간 결정).
- 목록 API 의 일 호출 한도 수치, 상세·이용 정보 한도가 엔드포인트별인지 합산인지 (data.go.kr 페이지에는 없음. 활용신청 상세 화면이나 신청서 확인).
- 첫 갱신에서 변경으로 잡히는 장소 수 (처음 한 번은 많을 수 있고, 한도 때문에 며칠에 나눠 처리됨).
- 현재 배포가 새 벡터 DB 로 재배포됐는지.
