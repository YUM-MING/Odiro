# 인수인계 문서

> 주차가 끝나면 **아래 양식을 복사해 맨 위에 새 섹션으로 추가**하고 push 한다. 최신이 위.
> 다음 담당자는 자기 주차 시작 전에 이 문서 → [TEAM_ROLES.md](TEAM_ROLES.md) → [DATA_AND_API.md](DATA_AND_API.md) 순으로 읽는다.

---

## 양식 (복사해서 쓰기)

```markdown
## N주차 → N+1주차 인수인계 (담당: 이름, 기간: MM/DD ~ MM/DD)

### 1. 한 줄 요약
### 2. 지금 상태
### 3. 매일 할 일 / 첫날 할 일
### 4. 완료한 것
### 5. 남은 일 (다음 담당자가 이어받을 것)
### 6. 알아야 할 것 (함정·결정 사항)
### 7. 자원 위치
### 8. 체크리스트 (push·빌드 통과 / 키·데이터가 git 에 없는지 / 데이터 tgz 전달 / 다음 담당자에게 알림)
```

---

## 2주차 → 3주차 인수인계 (담당: kingy0ujin, 기간: 11/14 ~ 11/21)

### 1. 한 줄 요약

**데이터 수집이 사람 손을 떠나 GitHub Actions 로 매일 자동(수집 → 버킷 업로드 → 배포)으로 돈다.** 이용 정보(휴무일·시간·요금·주차)와 한국관광공사 출처 표기가 들어갔고, 화면은 Day 탭·인원·시작 시간 변경 등으로 다듬었다. 마지막 날(11/21)에는 코스 품질 세 가지(분위기 요청 반영, 종료 시각 초과 수정, 평가 지표 정리)를 넣었다.
3주차의 일은 **① 실브라우저 점검·안정화 ② 시연 준비** 다. **더 이상 각자 PC 에서 수집을 돌리지 않는다** (아래 3번).

### 2. 지금 상태 (11/21 기준)

| 항목 | 상태 |
|---|---|
| 서비스 | https://odiro-where.web.app. `main` push 또는 매일 수집 뒤 자동 배포 |
| 일일 자동 수집 | `.github/workflows/daily-ingest.yml` — 매일 06:30(KST). 성공하면 같은 워크플로에서 `deploy.yml` 을 호출해 Cloud Run + Firebase 배포까지 한 번에 한다. 수집이 실패하면 업로드·배포를 건너뛴다 |
| 데이터 기준 | **GCS 버킷 `gs://odiro-where-data`** (`ingest-data.tgz`, `vectorstore.tgz`, `tour_intro.json`, 이전 판은 `backup/`). 로컬 파일이 아니다 |
| 장소 메타 | 전국 16개 시도 48,661건 |
| 장소 상세 (로컬 PC 에서 마지막으로 돌린 11/17 기준. 11/18 이후는 Actions 가 수집, 로컬 raw 에는 없음) | 서울 8,007/8,008 ✔ · 인천 1,984/1,987 ✔ · 경기 8,849/9,429 · 나머지 13개 시도 0. 이후는 Actions 가 이어서 받으므로 **최신 숫자는 버킷 기준** (받아서 `python scripts/daily_ingest.py --status`) |
| 이용 정보 (`detailIntro2`) | 11/17 기준 5,282건 (서울 2,038 · 인천 827 · 경기 2,565 + 이후 수집분). 쇼핑·음식점 제외 |
| 블로그 | 수도권 67,172건 그대로. 나머지 시도 블로그는 **미정** (비용·메모리) |
| 벡터 DB (11/17 기준) | 81,960청크 (장소 19,847 + 블로그 62,113). 이후는 Actions 가 버킷 판을 갱신 |
| 테스트 | `pytest` **141개** 통과 (11/21 확인). `ruff check odiro tests scripts` 는 **15건 지적**이 있다 (`tests/test_ingest_sync.py` 미사용 변수, `nodes.py` 루프 변수 바인딩 `B023` 등. 일부는 11/18 코드에도 있던 것이고 CI 는 ruff 를 돌리지 않아 배포는 막지 않는다) |
| git | 로컬 `main` 이 `origin/main` 보다 **4커밋 앞섬** (`c0c9bc3` 평가 스크립트 · `f078fa5` 미확인 지표 정의 · `7f599f2` 분위기 태그·블로그 근거 카페 · `aa8a802` 종료 시각 초과 수정). **push 전이라 사이트에는 아직 반영되지 않았다.** push 하면 배포가 한 번 돈다 |

### 3. 매일 할 일 / 첫날 할 일

#### 매일: 수집은 하지 않는다 — 결과만 확인

- 수집은 Actions 가 한다. **각자 PC 에서 `daily_ingest.py` 를 돌리면 로컬 데이터가 버킷과 갈라진다.** 상태를 보고 싶으면 버킷에서 받아서 `--status` 만 쓴다.
- 아침에 GitHub → Actions → `daily-ingest` 를 열어 **초록 체크인지, `deploy` 잡(backend·frontend)까지 돌았는지** 본다. 실패하면 로그를 보고 팀 채팅에 공유한다.
- 수동 실행: Actions → `daily-ingest` → Run workflow. 입력 두 개
  - `deploy` (기본 켜짐): 끄면 수집·업로드만 하고 배포는 안 한다
  - `force_removal`: 한 번에 5% 넘는 삭제도 반영. **대량 삭제가 사실임을 확인한 뒤에만**
- 한 번 실패한 날은 다음 날 이어서 받으므로 급하게 재실행하지 않아도 된다 (이미 받은 건 건너뜀).
- 필요한 설정 (이미 등록됨, 사라지면 수집이 멈춘다): Secrets `GCP_SA_KEY` · `TOUR_API_KEY` · `TOUR_API_KEYS_EXTRA` · `OPENAI_API_KEY`, Variables `CI_ENABLED=true` · `VECTORSTORE_GCS_URI=gs://odiro-where-data/vectorstore.tgz`. **`VECTORSTORE_GCS_URI` 가 비면 배포는 성공으로 뜨는데 새 데이터가 이미지에 안 들어간다.**

#### 첫날

1. 이 문서 → [PLAN_AUTO_INGEST.md](PLAN_AUTO_INGEST.md) → [README](../README.md) → [API_SCHEMA](API_SCHEMA.md) 를 읽는다.
2. 로컬 개발 환경: `.env` 는 메신저 비공개 노트에서 받는다. 데이터는 **버킷에서 받는다** (GCP 권한은 YUM-MING 에게 요청): `gcloud storage cp gs://odiro-where-data/ingest-data.tgz .` → `tar xzf ingest-data.tgz`, `gcloud storage cp gs://odiro-where-data/vectorstore.tgz .` → `tar xzf vectorstore.tgz -C data/`, `tour_intro.json` 은 `data/` 에 둔다.
3. `pytest` (141 passed), `python scripts/check_apis.py`, 백엔드 `uvicorn odiro.api.main:app --port 8000` + 프론트 `npm run dev` 로 `/plan` 까지 눌러 본다.
4. **Actions 탭에서 최근 `daily-ingest` 실행이 성공했는지부터 확인한다.**
5. Windows 에서 `npm run dev`/`lint` 가 네이티브 바인딩 오류를 내면 `npm install --no-save @rolldown/binding-win32-x64-msvc@<rolldown 버전>`, `@oxlint/binding-win32-x64-msvc@<oxlint 버전>` (`--no-save` 라 `package.json` 은 안 바뀐다).

### 4. 완료한 것

**데이터·수집**
- **TourAPI 403 해결**: 기본 키가 Encoding 키(`%` 포함)여서 막혔다 → Decoding 값으로 교체. 추가 키 2개와 함께 하루 약 3,000건
- 서울·인천 상세 완료, 경기 93.8% (11/17), **전국 16개 시도 메타 48,661건 확보**
- **이용 정보(`detailIntro2`) 수집**: `tour_api.py` 에 `normalize_intro`·`fetch_intro`·`collect_intro`. 종류별로 필드명이 달라(`restdate`/`restdateculture`…) 접두어로 흡수. 채움률은 쉬는 날·이용시간이 관광지·문화시설에서 96~99%, 반려동물은 거의 빔(화면에 안 씀)
- **조회 파일 방식**: 벡터화하지 않고 `scripts/build_intro_lookup.py` 가 `data/tour_intro.json` 을 만들고, 서버 `odiro/tools/tour_intro.py` 가 **이름 + 300m 이내** 로 찾아 `PlaceOut.intro` 로 붙인다. 지도 정보 창에 값이 있는 항목만 표시
- **변경·삭제 갱신** (`odiro/data/ingest/sync.py`): 장소별 `modifiedtime` 비교로 바뀐 건 재수집, 목록에서 사라진 건 상세·intro·라벨·벡터까지 삭제(purge 큐). 안전장치: 삭제가 저장 건수의 5%(최소 30건) 초과이거나 새 목록이 비면 중단(종료 코드 1). 하루 한 번만 목록 갱신
- **일일 자동 수집 워크플로** (`daily-ingest.yml`) + `deploy.yml` 의 `workflow_call`·`tour_intro.json` 다운로드. 이전 판은 버킷 `backup/` 에 한 세대 보관. 계획과 근거는 [PLAN_AUTO_INGEST.md](PLAN_AUTO_INGEST.md)
- 신청서 약속 이행: **출처 표기 "출처 : ⓒ한국관광공사"** 를 푸터·일정 화면·장소 카드·지도 정보 창에 추가 (운영계정 신청서에 매일 06:30 자동 동기화와 변경·삭제 갱신을 약속했었다)

**화면·기능**
- 공유: 포함할 조건을 체크박스로 고르고 일차별 전체 경로 링크 추가 (카카오톡 공유 연동은 만들었다가 제거함 — 카카오 공유는 제목·짧은 설명·링크만 보낼 수 있어 장소 목록을 못 싣고, 링크가 코스가 아닌 사이트 메인으로 가기 때문)
- 다시 만들기: 서버 결과 캐시를 건너뛰는 `refresh` 쿼리 파라미터. 조건 변경 후 이전 코스가 덮이는 버그 수정. 조건 드로어를 닫으면 조건만 적용(새 코스는 `다시 만들기`)
- 지도: 정보 창이 카카오 레이어에 가려지던 문제 수정(`z-index`), 핀 클릭 시 채팅 카드 스크롤, 하단 배너 제거
- 채팅 카드(큰 흐름) vs 지도 정보 창(세부사항) 역할 분리, 답변 글에서 카드와 겹치는 부분 숨김(`splitAnswer`)
- 여행 코스 **Day 탭**으로 카드·지도 분리, 주차장은 지도 정보 창으로, 첫 장소 정보 창 자동 표시
- 예산에 **총 인원** 반영 (1인 예산 × 인원), 진행 화면에서 코스를 만드는 중에도 접기/펼치기
- 채팅으로 **일정 시작 시간 변경** (`day_starts`), 시작 시간이 임의로 고정되던 버그 수정

**코스 품질 (11/21, 커밋 `7f599f2` · `aa8a802`, push 전)**
- **분위기 요청 반영**: 자유 문장("조용한 카페로 바꿔줘")을 분위기 태그로 바꾸는 `_extract_moods` (gpt-4o, 태그마다 문장에서 인용한 표현이 실제 문장에 있어야 인정해 오탐 방지). 처음 생성은 선택 태그에 합치고, 수정은 그 태그로 RAG 를 새로 검색. 분위기 요청이 있으면 태그 붙은 블로그 제목에서 카페 상호를 뽑아 카카오로 찾아 후보 맨 위에 올림(뚜벅이 중심 800m 이내). 근거 없는 곳은 분위기를 단정하지 않게 프롬프트 규칙 추가
- `_find_must` 가 "조용한 카페" 같은 분위기 표현을 필수 장소로 강제하던 문제 수정
- `rag_search`: Chroma 클라이언트 생성을 락으로 직렬화 (RAG 를 두 스레드가 동시에 호출하면 초기화가 깨졌다)
- **종료 시각 초과 수정**: 시각을 분 단위로 누적해 자정을 넘겨도 경고가 사라지지 않게 함. 초과하면 숙소를 뺀 마지막 장소부터 덜어내고 이동 구간 재계산. 숙소 체류는 종료 판정에서 제외, 하루 장소 수는 올림 대신 내림
- 효과를 숫자로 입증하지는 못했다. 분위기 변경은 전후 비교에서 규칙 지표 변화가 없었고 시간이 1~3초 늘었다. 카페가 더 낫다는 것은 지표가 없어 모른다. 종료 시각 수정은 "전" 결과가 없어 효과를 증명하지 못했다 ([EVAL_COURSES.md](EVAL_COURSES.md) 5-1, 5-2)

**평가**
- `scripts/eval_courses.py`: 시나리오 10개(수도권 안팎, 도보·자차·여행 등)로 확인 안 된 장소 수, 반경 밖 비율, 식당·카페 구성, 응답 시간을 표로. 테스트 `tests/test_eval_courses.py`. 11/17 까지 수집한 데이터로 11/18 에 돌려 기준선을 남겼다: 반경밖 0%, 구성 미흡 0건, 예산 초과 0건, 평균 33.1초(2일 여행은 40~47초), 미확인 장소 2건. 이 2건은 TourAPI 큐레이션 장소가 카카오 ID 없이 들어간 것이라 11/21 에 **미확인 지표 정의에서 ID 조건을 뺐고**(코드는 안 바꿈), `종료초과` 열을 추가했다. 가장 최근(11/21 11:44, 출발일 11/23): 미확인·반경밖·예산 초과·구성 미흡·종료 초과 모두 0건, 평균 27.1초·최대 38.8초. 단 시나리오당 1회 결과이고 LLM 변동이 있다. 사용법·표·해석은 [EVAL_COURSES.md](EVAL_COURSES.md). 돌릴 때마다 시나리오 10개 약 100~200원이 든다

### 5. 남은 일 (다음 담당자가 이어받을 것)

3주차 본업은 [TEAM_ROLES.md](TEAM_ROLES.md) 3주차를 따른다. 2주차 계획 중 코스 품질(Day 3)·응답 시간(Day 4)·나머지 시도 블로그(Day 6)는 평가 결과를 보고 **보류**했다(근거는 TEAM_ROLES 2주차). 이어받을 것은 아래 셋이다. (코스 품질 일부는 11/21 에 진행했다 — 위 4번)

1. **평가 스크립트로 전후 비교** — 기준선은 11/18, 최근 결과는 11/21 이다([EVAL_COURSES.md](EVAL_COURSES.md) 5, 5-1, 5-2). 코스 품질을 건드리면 같은 `--date` 로 돌려 비교한다. 미확인 지표 정의가 11/21 에 바뀌어서 11/18 표의 "미확인 2건"은 옛 정의 기준이다
2. **TourAPI 운영계정 승인 확인** — 승인되면 `daily-ingest.yml` 의 Ingest 단계에 `--daily-limit 10000` 추가 (승인 전에는 넣지 않는다)

3. **코스 품질 남은 문제** (미확인 장소 건은 11/21 에 정리: 빈 자리를 TourAPI 큐레이션 장소로 채우는 경로(`verify_places` 의 `known_used`·`play_added`·`meals_fixed`)가 카카오 ID 없이 `verified=True` 로 넣는 것이 원인이었고, 공식 데이터라 그대로 두고 평가 지표만 고쳤다. `nodes.py` 에 카카오 검증을 넣는 시도는 되돌렸다)
   - (a) 같은 가게가 카카오 확인본과 TourAPI 관광지로 **이름만 달리 두 번** 들어갈 수 있다 (가평 "카페 드 모파상"). 이름 정규화 비교나 좌표 근접 비교로 풀 수 있다
   - (b) `songdo_family` 는 자차+아이 동반으로 장소가 4곳뿐이라 카페 0곳(구성 미흡)이 **가끔** 나온다 (4회 반복에서 1회, 분위기 변경 전에도 있던 변동). 카페가 검증에서 탈락하거나 식당·카페 수 보정이 카페 자리를 볼거리로 바꾸는 것으로 추정할 뿐 코드 경로는 확인하지 않았다
   - (c) 평가 스크립트에 "카페의 블로그 근거 비율" 지표가 없어 분위기 변경이 더 나은지 모른다. 결과 JSON 에 경고 문구가 저장되지 않아 "종료 시각 때문에 장소를 뺐는지"도 못 센다

여유가 있을 때만: 추천 이유의 근거 없는 수식(분위기 단정 금지 규칙은 프롬프트에 넣었지만 측정 수단이 없다), 응답 시간(2일 여행이 38~42초로 목표 40초 경계). 응답 시간은 먼저 `meta.trace` 로 `compose_answer` 비중을 측정한다.

### 6. 알아야 할 것 (함정·결정 사항)

**자동 수집**
- **상태의 기준은 버킷이다.** 워크플로는 받아서 이어 돌리고 성공하면 다시 올린다. 상태 파일(`ingest-data.tgz`)을 **마지막에** 올려서 중간에 끊겨도 다음 실행이 이어진다. 버킷에 `ingest-data.tgz` 가 없으면 처음부터 시작하지 않고 실패한다 (전체 재수집은 한도·비용이 크다)
- 실패하면 업로드·배포 둘 다 안 된다 → 사이트는 어제 데이터로 유지된다 (깨진 데이터가 안 올라가는 것은 의도)
- 삭제 중단(종료 코드 1)이 뜨면 먼저 TourAPI 쪽이 정말 대량 삭제했는지 확인하고 `force_removal` 을 쓴다
- cron 은 **기본 브랜치(main)** 의 워크플로만 돈다. GitHub 예약 실행은 몇 분~수십 분 늦을 수 있다
- `deploy.yml` 은 `--source .` 로 새로 빌드해 배포한다 (약 12분). 수집이 성공할 때마다 Cloud Run 빌드 비용·시간이 든다
- TourAPI 한도는 **엔드포인트별** 일 1,000건/키 (`detailIntro2` 는 `detailCommon2` 와 별도, 키 3개 합계가 하루 약 3,000건 — 한도 단위는 합산인지 끝까지 확인하진 못했다). 자정(KST)에 초기화
- 서비스 키가 든 URL 이 로그에 찍히지 않게 새 스크립트에서도 `setup_logging` 을 쓴다. `check_apis.py` 는 실패 시 키가 든 URL 을 출력하는 문제가 있다 (11/14 에 기본 키가 대화에 노출된 적이 있어 **재발급 검토 대상**)

**코드**
- 이용 정보는 **원문 그대로** 저장·표시한다. AI 가 고쳐 쓴 값을 관광공사 출처로 내면 안 된다 (원문 훼손 금지)
- `data/tour_intro.json` 은 git 에도 있지만 배포는 버킷 판을 우선 쓴다 (없으면 git 판). git 판은 초기값이다
- `rag_search` 의 시군구 해석이 `cache/ingest_state/sigungu_*.json` 에 의존한다 — 지우면 지역 해석이 깨진다
- 같은 요청은 7일 결과 캐시. `다시 만들기` 는 캐시를 건너뛰지만 **도구 캐시(`cache/tools`)는 그대로**라 LLM 초안만 달라진다
- **분위기 요청 처리(`_extract_moods`, `_find_must`)는 gpt-4o 를 쓴다.** 코스 1건당 LLM 호출이 늘어 시간이 1~3초 늘었고 비용도 늘었을 수 있다("코스 1건 10~20원"은 이 변경 전 수치이고 다시 재지 않았다)
- `Plan.tsx`, `Plan.css` 는 CRLF 와 LF 가 섞여 있다 (동작엔 영향 없음)
- 기본 TourAPI 키는 반드시 Decoding 키. 원본 `Desktop\Odiro\.env` 를 다시 복사하면 Encoding 키로 되돌아간다

**결정 사항**
- 이용 정보는 벡터화하지 않고 조회 파일 방식 (정형 필드라 임베딩 불필요)
- 쇼핑(38)·음식점(39)은 이용 정보 수집에서 제외 (식당·카페는 카카오에서 오고, 쇼핑은 시장·상가가 대부분)
- 카카오톡 공유 SDK 는 보류 (코스를 서버에 저장하는 공유 URL 이 먼저 필요)
- 사진은 화면에 쓰지 않는다 (필요하면 지도 정보 창 썸네일 + `http`→`https` 변환 시험)

### 7. 자원 위치

| 항목 | 위치 |
|---|---|
| 서비스 | https://odiro-where.web.app |
| 자동 수집·배포 기록 | https://github.com/YUM-MING/Odiro/actions (`daily-ingest`, `deploy`) |
| 데이터 버킷 | `gs://odiro-where-data/` — https://console.cloud.google.com/storage/browser/odiro-where-data?project=odiro-where (버킷 단위 권한이라 목록 화면은 안 열리는 게 정상, 직접 주소로 접속) |
| 수집 계획·근거 | [PLAN_AUTO_INGEST.md](PLAN_AUTO_INGEST.md) |
| 평가 | `python scripts/eval_courses.py` |
| API 키 | 메신저 비공개 노트 (`.env`). GitHub Secrets 는 Actions 전용이라 로컬로 안 내려온다 |
| 데이터 tgz | **더 이상 따로 전달하지 않는다.** 버킷에서 받는다 (3번 첫날 2) |

### 8. 체크리스트

- [x] `pytest` 141 통과
- [ ] 로컬 `main` **4커밋 push 전** (`c0c9bc3` · `f078fa5` · `7f599f2` · `aa8a802`) — push 하면 배포가 돈다. 프론트 변경은 없고 백엔드(코스 생성)가 바뀐다. 배포 후 코스를 몇 번 만들어 보고 `ruff` 지적 15건은 3주차에 정리할지 정한다
- [x] `.env`·데이터가 git 에 안 들어갔는지 확인 (`data/vectorstore.20261117-18/` 등 untracked 폴더는 커밋 금지)
- [x] 데이터 전달 방식: tgz 대신 버킷 기준
- [ ] 다음 담당자에게 `.env` 전달, GCP·GitHub 권한 부여, 메신저로 알림

---

## 1주차 → 2주차 인수인계 (담당: YUM-MING, 기간: 11/04 ~ 11/13)

### 1. 한 줄 요약

**조건을 넣으면 실존 확인된 장소로 코스를 짜서 지도에 보여 주고 대화로 고치는 전 과정이 https://odiro-where.web.app 에서 돌아간다.**
원래 1주차 범위(데이터)를 넘어 에이전트·API·프론트 1차 구현과 배포까지 끝냈다.
2주차의 일은 "만들기" 가 아니라 **① 매일 TourAPI 상세 수집(전국까지) ② 코스 품질 ③ 평가·테스트** 다.

### 2. 지금 상태 (11/13 기준)

| 항목 | 상태 |
|---|---|
| 서비스 | https://odiro-where.web.app — 코스 생성·수정·지도 동작. `main` 에 push 하면 자동 배포(약 12분) |
| 백엔드 | Cloud Run `odiro-api`, 메모리 **4Gi**(2Gi 는 코스 생성 중 메모리 초과로 죽는다), 최소 인스턴스 0. API 키·모델 설정 환경변수 15개 등록됨 |
| 장소 메타 | 수도권 19,424건 (서울 8,008 · 인천 1,987 · 경기 9,429). 나머지 13개 시도는 아직 없음 |
| 장소 상세 | **서울 6,995 / 8,008** (남은 1,013건은 전부 쇼핑). 인천·경기 0 |
| 블로그 | 수도권 67,172건, 라벨링 완료 |
| 벡터 DB (로컬) | 69,479청크, 741MB (장소 7,366 + 블로그 62,113) |
| 벡터 DB (배포) | 11/13 판 69,479청크 (`gs://odiro-where-data/vectorstore.tgz`, 11/13 업로드·배포). 이후 수집분은 3번 "벡터 DB 올리기" 로 반영 |
| 테스트 | `pytest` 83개(네트워크 없음), `ruff`, 프론트 `npm run lint` · `npm run build` 통과 |

### 3. 매일 할 일 / 첫날 할 일

#### 매일 (11/14 토요일부터): TourAPI 상세 수집

```bash
python scripts/daily_ingest.py            # 수집 → 라벨링 → 로컬 인덱스까지 한 번에 (약 20분)
python scripts/daily_ingest.py --status   # 시도별 진행 현황만 (API 호출 없음)
```

- **순서는 서울 → 인천 → 경기 → 나머지 시도.** 앞 지역이 끝나야 다음으로 넘어간다. 메타가 없는 시도는 스크립트가 메타부터 받는다.
- **하루 약 3,000건.** TourAPI 개발계정은 키마다 상세 조회 일 1,000건이고, `.env` 에 키 3개(`TOUR_API_KEY` + `TOUR_API_KEYS_EXTRA` 2개)가 들어 있다. 기본 키를 먼저 쓰고 나머지를 이어 쓴다.
- 한도는 **자정(한국 시간)에 초기화**된다. 이미 받은 건 건너뛰므로 여러 번 돌려도 안전하고, 하루 빠뜨려도 다음 날 이어서 받는다.
- 비용: 라벨링·임베딩이 `OPENAI_API_KEY` 로 나간다. 3,000건에 300~500원.
- 예상 일정: 수도권 남은 12,429건 → **11/14 ~ 11/18 (5일)**. 나머지 13개 시도는 메타를 받아 봐야 알지만 4~5만 건으로 추정 → 하루 3,000건이면 2~3주. 줄이려면
  - 쇼핑(38)을 빼고 받는다: `python scripts/daily_ingest.py --types 12 14 39 28 15 32 25` (서울 쇼핑만 4,391건이었고 대부분 시장·상가다)
  - 기본 키의 운영계정 전환이 승인되면 `--daily-limit <새 한도>` 를 붙인다 (11/12 시점엔 미승인: 1,000건을 넘기면 서버가 429 로 거절)
  - 팀원 키를 `TOUR_API_KEYS_EXTRA` 에 더 넣는다 (쉼표 구분, 일반 인증키)

#### 벡터 DB 올리기 (배포 사이트에 반영, 주 1~2회나 지역 하나가 끝났을 때)

로컬 인덱스는 배포에 자동 반영되지 않는다. 백엔드 서버(uvicorn)를 끈 상태에서:

```bash
tar czf vectorstore.tgz -C data vectorstore
gcloud storage cp vectorstore.tgz gs://odiro-where-data/vectorstore.tgz --project odiro-where
gh workflow run deploy --repo YUM-MING/Odiro      # 또는 아무 커밋이나 push
```

배포 후 `gcloud logging read 'resource.labels.service_name="odiro-api" AND severity>=WARNING' --limit 20` 에 `Memory limit` 가 없는지 본다.
인덱스가 커질수록 메모리를 더 쓴다 (63k 청크일 때 검색만 약 1.1GB). 전국 블로그까지 넣으면 4Gi 로도 모자랄 수 있다 — 5번 참고.

#### 첫날

1. 이 문서 → [README](../README.md) → [API_SCHEMA](API_SCHEMA.md) 를 읽는다.
2. `.env` 완성본은 메신저 비공개 노트에서 받는다. 데이터는 7번의 tgz 두 개를 레포 루트에서 푼다 (`tar xzf odiro-data-20261113.tgz` , `tar xzf vectorstore-20261113.tgz -C data/`).
3. `pytest` (83 passed), `python scripts/check_apis.py` (전부 OK), `python -m odiro.agent.run "성수동"`, 프론트 `npm run dev` 로 `/plan` 까지 눌러 본다.
4. `python scripts/daily_ingest.py --status` 가 위 표와 같은 숫자를 내는지 확인하고, 그날 치 수집을 돌린다.
5. GCP·GitHub 권한이 필요하면 YUM-MING 에게 요청한다 (GCP 프로젝트 `odiro-where` 편집자, GitHub Collaborator).

### 4. 완료한 것

- **API 키 10종 발급·검증**, Cloud Run 환경변수 등록, 카카오 JavaScript SDK 도메인 등록 (`https://odiro-where.web.app`, `http://localhost:5173`)
- **데이터 파이프라인** `odiro/data/ingest/` (`tour_api` · `naver_blog` · `labeling` · `build_index`): 전부 재실행 안전, 지역 인자 `--area` / `--all`. TourAPI 키 여러 개 지원. 하루치 묶음 실행 `scripts/daily_ingest.py`
- **Tool 6개** `odiro/tools/`: `rag_search`(태그·지역 필터) · `search_place`(카카오 실존 검증) · `get_route` · `get_sun_times` · `get_weather` · `summarize_reviews`. 전부 캐시 + 8초 타임아웃
- **에이전트** `odiro/agent/` (LangGraph): `parse_intent → retrieve → draft_course → verify_places → optimize_route → enrich → compose_answer`, 수정은 `modify → verify_places → …`
  - 실존 검증: 지도에 없는 장소는 예비 후보 → LLM 보충 → 실존 확인된 후보 순으로 채워 **장소 수를 유지**하고, 확인 안 된 장소는 응답에 넣지 않는다
  - 자유 조건이 장소 종류를 가리키면(예: 반지공방, 라구파스타) 지도에서 찾아 **코스 전체에 한 번** 넣는다
  - 여행 모드: 숙소 직접 입력 또는 자동 선택, 가까운 장소끼리 같은 날로 묶기, 전날 숙소 기준 동선
  - 비 예보면 야외 장소를 하루 1곳(자연/산책 태그면 2곳)까지로 줄이고 실내로 바꾼다
  - 뚜벅이는 반경 1.5km, 동선 중심에서 1.1km 넘는 장소는 교체. 동 단위 자차 요청("인천 송도")은 반경 8km
  - 하루에 식당·카페 각 2곳까지, 식당이 연달아 나오면 시간대 순서(볼거리 → 점심 → 카페 → … → 저녁)로 재정렬. 볼거리가 없는 날은 하나 넣는다
  - 프랜차이즈(메가커피·스타벅스·맥도날드 등 `_CHAINS`) 제외. 자유 조건에 이름을 적으면 허용
  - 자차: 장소별 가장 가까운 주차장(카카오, 400m 안). 장소별 1인 예상 비용(LLM 추정)·합계·예산 초과 경고
  - 수정: "N번째/마지막" 은 코드에서 대상 확정, 교체 후보가 지도에 없으면 업종 검색 → 같은 역할의 근처 실존 장소로 반드시 대체
- **API** FastAPI: `/api/course(/start)`, `/api/course/stream/{job}`(SSE), `/api/course/edit(/start)`. 계약은 [API_SCHEMA](API_SCHEMA.md)
- **프론트** React: 조건 빌더(여행 모드 숙소 입력) → `/plan` (진행 표시는 완성 후 접힘, 밥집·카페·놀거리·숙소 색 구분 카드와 지도 핀, 리뷰 보기·길찾기 링크, Day 별 카카오맵 내비 경로, 예상 비용/예산, 바꾸기·빠른 수정·자유 수정, 공유)
- **배포**: GitHub Actions 자동 배포(`.github/workflows/deploy.yml`), 벡터 DB 는 GCS 에서 받아 이미지에 포함

### 5. 남은 일 (우선순위 순)

1. **매일 수집** (3번). 수도권 → 전국.
2. **나머지 시도 블로그** — `python -m odiro.data.ingest.naver_blog --all` → `labeling --all --only blog` → `build_index --all`. 라벨링이 1만 건당 약 1달러라 수도권 규모(6.7만 건)로 전국을 하면 15~30달러 + 인덱스가 2~3배가 된다. **예산과 Cloud Run 메모리를 보고 샘플링**할 것 (예: `--per-query 30` 만, 또는 장소 문서만 전국으로).
3. **TourAPI 소개 정보(`detailIntro2`) 수집** — 실제 휴무일·이용요금·주차·반려동물 동반 여부가 여기에 있다. 지금은 이 정보가 없어서 휴무일은 "방문 전 확인" 안내만, 비용은 LLM 추정, 웨이팅·반려동물은 블로그 태그 수준이다. `tour_api.py` 에 기능을 추가하고(상세와 한도가 따로다) 에이전트가 쓰게 하면 추정이 사실로 바뀐다.
4. **코스 품질**
   - 추천 이유에 "분위기가 좋다" 류의 근거 없는 수식이 섞인다 (프롬프트 규칙으로만 막는 중)
   - 리뷰 요약이 비는 장소가 40~60% (수도권 밖은 거의 전부). 틀린 요약 대신 비워 두게 해 놓았다
   - 수도권 밖은 큐레이션 문서가 없어 볼거리를 지도 검색(관광명소·문화시설)으로 채운다 → 설명이 "이 지역에서 들러 볼 만한 곳 (박물관)" 처럼 밋밋하다. 수집이 진행되면 나아진다
   - 예상 비용이 예산을 넘어도 경고만 하고 코스를 줄이지 않는다
   - 프랜차이즈 목록에 없는 브랜드는 걸러지지 않는다
   - 여행 모드에서 하루 장소 수가 한쪽으로 쏠리거나 종료 시각을 넘기는 날이 있다
5. **응답 시간** — 생성 50~90초, 수정 15~35초 (11/12 라이브). 초안·답변 작성 LLM 을 더 빠른 모델로 나누거나 답변을 스트리밍. 노드별 시간은 응답의 `meta.trace`
6. **평가 스크립트** — 시나리오 10개를 돌려 확인 안 된 장소 0건, 반경 밖 비율, 식당·카페 구성, 응답 시간을 표로. 지금은 사람이 눈으로 본다
7. **미확인** — 11/12 에 넣은 화면 변경(진행도 접기·색 구분·링크·내비)은 빌드·배포만 확인했고 브라우저에서 끝까지 눌러 보지 않았다. 동시 요청(여러 명이 한꺼번에 생성)은 4Gi 에서 시험하지 않았다. 서버가 죽었을 때 프론트가 어떻게 보이는지도 미확인
8. TourAPI **운영계정 전환 신청** 결과 확인 (data.go.kr → 마이페이지 → 해당 API)
9. 발표용 그래프 이미지: `python -m odiro.agent.graph` 출력(Mermaid)을 https://mermaid.live 에서 PNG 로

### 6. 알아야 할 것 (함정·결정 사항)

**키·콘솔**
- TourAPI 키는 **일반 인증키(Decoding)**. `%` 가 들어간 Encoding 키는 코드가 거부한다. 64자리 16진수 신형 키는 그대로 쓰면 된다
- 네이버 검색 API 는 **NCP NAVER API HUB** 에서 발급한다 (엔드포인트·헤더가 예전과 다름, 코드 반영됨)
- 카카오 지도 도메인 등록 메뉴는 "플랫폼 → Web" 이 아니라 **JavaScript SDK 도메인**. 안 하면 지도 패널만 빈다
- Kakao Local 403 `disabled OPEN_MAP_AND_LOCAL` → 카카오 디벨로퍼스 앱에서 카카오맵 활성화. Tmap 403 → openapi.sk.com 프로젝트에 TMAP 상품 연결
- `.env` 를 바꾸면 `python scripts/push_env_to_cloudrun.py` 로 Cloud Run 에 다시 올린다. `TOUR_API_KEYS_EXTRA` 는 수집 전용이라 올릴 필요 없다
- 팀원이 로컬에서 에이전트를 돌리려면 각자 `.env` 가 있어야 한다. Cloud Run 의 키나 GitHub Secret 은 로컬로 내려오지 않는다

**비용**
- 라벨링·임베딩·코스 생성은 전부 `OPENAI_API_KEY` 계정. 코스 1건 10~20원. 1주차 총 약 4~6달러였고 이후 일일 수집은 하루 300~500원
- Cloud Run 은 요청 처리 시간만큼 과금. 월 무료 한도(메모리 36만 GiB·초) 안이면 0원이고 4Gi 기준 코스 약 2,000건 분량이다 (요금표 재확인 필요)
- **최소 인스턴스는 0 유지.** 시연 당일만 1 로 올리고 끝나면 내린다 (1 로 두면 월 1~2만 원)
- `main` 에 push 할 때마다 배포(빌드 12분)가 돈다. 문서만 고칠 때는 모아서 push

**코드**
- TourAPI 는 `lDongRegnCd`(법정동 시도코드: 서울 11 · 인천 28 · 경기 41) 를 쓴다. 구 `areaCode` 는 1/8 만 나온다
- 큐레이션 **장소 문서는 TourAPI 상세가 있는 곳만** 인덱스에 들어간다. 그래서 상세가 없는 지역은 볼거리 후보가 비고 지도 검색으로 대신한다 (`nodes._find_attractions`)
- LangGraph 는 상태 스키마(`agent/state.py` `CourseState`)에 없는 키를 **조용히 버린다**. 노드가 새 키를 돌려주면 스키마에도 추가할 것 (예비 후보가 이 때문에 전달되지 않던 버그가 있었다)
- 같은 요청은 7일 캐시(`cache/tools`). 결과가 안 바뀌면 `--no-cache` 또는 `cache/tools` 삭제. Cloud Run 은 컨테이너가 뜰 때마다 캐시가 빈다
- 프론트는 SSE 때문에 Cloud Run 을 **직접** 호출한다 (`VITE_API_URL`). Hosting rewrite 는 응답을 버퍼링해 진행 표시가 안 된다
- 서버가 메모리 초과로 죽으면 `error` 이벤트 없이 SSE 만 닫힌다
- httpx 는 INFO 로그에 요청 URL 전체(서비스 키 포함)를 찍는다 → `setup_logging` 이 꺼 둔다. 새 스크립트에서도 끌 것
- 타지역 블로그 글 필터 `OTHER_REGION_WORDS`, 시도 별칭 `rag_search._SIDO_ALIASES` 는 수도권 기준이다. 전국 확장 때 손봐야 한다
- Windows 에서 Claude Code 의 `!` 명령은 Git Bash 로 돈다 → 경로는 `./.venv/Scripts/python.exe` 처럼 슬래시로

**결정 사항**
- 서비스 목표는 전국, 데이터는 서울 → 인천 → 경기 → 나머지 시도 순으로 채운다
- 브랜치 없이 `main` 에 바로 커밋·push (주 1명 담당)
- 로그인·회원가입은 넣지 않는다
- 인스타그램·예약 앱 직접 크롤링은 하지 않는다

### 7. 자원 위치

| 항목 | 위치 |
|---|---|
| 서비스 | https://odiro-where.web.app |
| 백엔드 직접 URL | https://odiro-api-80160454962.asia-northeast3.run.app (`/api/health`, `/api/config-check`) |
| GitHub | https://github.com/YUM-MING/Odiro (`main`), 배포 기록 `/actions` |
| GCP 프로젝트 | `odiro-where` — Cloud Run https://console.cloud.google.com/run?project=odiro-where , 버킷 `gs://odiro-where-data` |
| 원본 데이터 + 수집 상태 | `odiro-data-20261113.tgz` (28MB: `data/raw`, `cache/ingest_state`) — **YUM-MING 이 Drive 에 올리고 링크를 여기에 기입** |
| 벡터 DB (11/13, 69,479청크) | `vectorstore-20261113.tgz` (500MB) — 위와 같이 Drive. 배포용 `gs://odiro-where-data/vectorstore.tgz` 도 같은 판 (GCP 권한이 있으면 여기서 받아도 된다) |
| API 키 | 메신저 비공개 노트 (`.env` 완성본, TourAPI 키 3개 포함) |
| 시연 캐시 | `python scripts/warm_demo_cache.py --date <시연일>` → `cache/demo/*.json` |

### 8. 체크리스트

- [x] `main` 에 push 됐고 빌드 통과 (`pytest` 83, `ruff`, `npm run lint`, `npm run build`)
- [x] `.env`·데이터가 git 에 안 들어갔는지 확인
- [ ] 데이터 tgz 두 개를 Drive 에 올리고 7번에 링크 기입 (파일은 `C:\Users\LYM\odiro-release\` 에 만들어 둠)
- [x] 11/13 벡터 DB 를 GCS 에 올리고 배포
- [ ] 다음 담당자에게 `.env` 전달 + 메신저로 알림

---

## 0주차 → 1주차 인수인계 (담당: Claude, 기간: 11/04)

### 1. 한 줄 요약
레포·배포 파이프라인·랜딩 페이지가 완성되어 **https://odiro-where.web.app** 에서 프론트와 백엔드(`/api/health`)가 연결된 상태로 돌아간다. 데이터·에이전트는 아직 뼈대만 있다.

### 2. 완료한 것
- [x] GitHub `YUM-MING/Odiro` main 브랜치에 코드 정리 (커밋 `f1c3cc2`)
- [x] **프론트 배포**: Firebase Hosting (`frontend/firebase.json`, `.firebaserc` → 프로젝트 `odiro-where`)
- [x] **백엔드 배포**: Cloud Run `odiro-api` (서울 `asia-northeast3`), 최소 0 / 최대 1 인스턴스, 공개 호출 허용. Hosting 의 `/api/**` 가 여기로 rewrite 되어 CORS 문제 없음
- [x] **랜딩 페이지**: `docs/reference-landing.png` 시안 기준으로 구현 (`frontend/src/App.tsx`, `App.css`, `HeroScene.tsx`, `Icons.tsx`). 검색 카드의 버튼은 **아직 동작 안 함** (3주차가 조건 빌더로 연결)
- [x] 비용 안전장치: 결제 계정에 월 5,000원 예산 알림. `README.md` 배포 섹션에 비용 주의사항
- [x] Docker 이미지 로컬 빌드·헬스체크 확인, `.dockerignore`/`.gcloudignore`
- [x] 문서: `docs/TEAM_ROLES.md`, `docs/DATA_AND_API.md`, 이 문서
- [x] GitHub Actions 자동 배포 워크플로 파일 작성 (`.github/workflows/deploy.yml`) — **활성화는 아래 3번 참고**

### 3. 못 한 것 / 미뤄진 것
- [ ] **API 키 전부 미발급** — 사이트 하단에 "API 키 9개 미설정" 표시 중. 1주차 Day 1 작업
- [ ] **자동 배포 활성화** — 워크플로 파일은 있지만 GitHub 에 GCP 서비스 계정 키(`GCP_SA_KEY`)가 등록되지 않아 아직 꺼져 있음. 권한을 부여하는 작업이라 사람이 직접 해야 한다. 아래 4-3 참고. 그 전까지는 **수동 배포** (README 참고)
- [ ] 팀원 GCP/Firebase 접근 권한 — 팀원 A·B 의 구글 계정을 프로젝트에 추가해야 콘솔에서 로그·환경변수를 볼 수 있음 (4-2)
- [ ] `odiro/data/ingest/`, `odiro/tools/` 는 docstring 만 있는 빈 패키지. `odiro/agent/graph.py` 는 노드가 전부 `lambda s: s` 더미

### 4. 다음 담당자(1주차)가 첫날 해야 할 것
1. **TourAPI 활용신청 + 운영계정 트래픽 증량 신청** (`docs/DATA_AND_API.md` 6번). 승인에 1~3일 걸리므로 무조건 오늘.
2. Kakao(REST·JS·Mobility), 네이버, OpenAI 키 발급 → `.env` 채우고 `python scripts/check_apis.py`
3. 팀원 접근 권한 추가:
   - GCP: https://console.cloud.google.com/iam-admin/iam?project=odiro-where → 액세스 권한 부여 → 팀원 이메일, 역할 **편집자**
   - Firebase: https://console.firebase.google.com/project/odiro-where/settings/iam → 구성원 추가
   - GitHub: 레포 Settings → Collaborators → 팀원 추가
4. (선택, 10분) 자동 배포 켜기 — Cloud Shell 에서 아래 실행 후 출력되는 안내대로 GitHub Secret 등록:
   ```bash
   bash scripts/setup_ci.sh
   ```
   끝나면 `main` 에 push 할 때마다 프론트·백엔드가 자동 배포된다. 안 켜도 개발엔 지장 없음.
5. `docs/TEAM_ROLES.md` 의 1주차 Day 2 부터 진행.

### 5. 알아야 할 것 (함정·결정 사항)
- **팀원이 로컬에서 클론 → 작업 → push 해도 사이트에 바로 반영되지 않는다.** 반영 경로는 둘 중 하나:
  - (a) 자동 배포를 켜면 `main` push ≈ 3~5분 후 반영.
  - (b) 안 켜면 담당자가 Cloud Shell 또는 로컬에서 `firebase deploy` / `gcloud run deploy` 를 직접 실행 (README 명령어). 로컬에서 하려면 `gcloud auth login`, `firebase login` 필요.
- 로컬 개발은 배포와 무관하게 `uvicorn` + `npm run dev` 로 즉시 확인 가능 (README). 매번 배포할 필요 없음.
- **Cloud Run 최소 인스턴스는 0 유지.** 1로 올리면 월 1~2만 원. 시연 당일만 올리고 끝나면 내릴 것.
- `.env` 는 Docker 이미지에 들어가지 않는다. 배포 환경 키는 Cloud Run 콘솔 환경변수로만 넣는다.
- 프론트 `index.html` 이 Pretendard 폰트를 CDN 에서 받는다. 오프라인 시연이면 로컬 폰트로 바꿀 것 (3주차).
- Kakao JS 키는 도메인 제한이 보호 수단이므로 Kakao 콘솔에 `https://odiro-where.web.app` 과 `http://localhost:5173` 을 꼭 등록.
- Phase 0 의 `/api/config-check` 는 키 이름만 노출하고 값은 노출하지 않는다. 그래도 서비스 오픈 시엔 제거 권장.
- 0주차 작업 중 Cloud Shell `~/.bash_history` 에 Anthropic API 키가 평문으로 남아 있었음 → **해당 키는 폐기하고 재발급** 할 것. 새 키는 절대 명령줄에 직접 치지 말고 `.env` 에만.

### 6. 자원 위치
| 항목 | 위치 |
|---|---|
| 서비스 | https://odiro-where.web.app |
| 백엔드 직접 URL | https://odiro-api-80160454962.asia-northeast3.run.app (헬스: `/api/health`) |
| GCP 프로젝트 | `odiro-where` (https://console.cloud.google.com/run?project=odiro-where) |
| Firebase 콘솔 | https://console.firebase.google.com/project/odiro-where |
| GitHub | https://github.com/YUM-MING/Odiro |
| 디자인 레퍼런스 | `docs/reference-landing.png` |
| 기획서 | `PLAN.md` |
| API 키 | 아직 없음 → 1주차가 발급 후 메신저 비공개 노트 |
| 데이터 tgz | 아직 없음 |

### 7. 체크리스트
- [x] `main` 에 push 됐고 빌드 통과 (`npm run build`, `npm run lint`, Docker 빌드)
- [x] `.env`·데이터가 git 에 안 들어갔는지 확인
- [ ] 데이터 tgz — 해당 없음 (0주차)
- [x] 다음 담당자에게 알림 (이 대화)
