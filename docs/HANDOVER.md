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
| 벡터 DB (배포) | **11/11 판 63,347청크** — 11/12~13 수집분은 아직 배포에 없다 (3번 "벡터 DB 올리기") |
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
| 벡터 DB (11/13, 69,479청크) | `vectorstore-20261113.tgz` (500MB) — 위와 같이 Drive. 배포용 `gs://odiro-where-data/vectorstore.tgz` 는 아직 11/11 판 |
| API 키 | 메신저 비공개 노트 (`.env` 완성본, TourAPI 키 3개 포함) |
| 시연 캐시 | `python scripts/warm_demo_cache.py --date <시연일>` → `cache/demo/*.json` |

### 8. 체크리스트

- [x] `main` 에 push 됐고 빌드 통과 (`pytest` 83, `ruff`, `npm run lint`, `npm run build`)
- [x] `.env`·데이터가 git 에 안 들어갔는지 확인
- [ ] 데이터 tgz 두 개를 Drive 에 올리고 7번에 링크 기입 (파일은 `C:\Users\LYM\odiro-release\` 에 만들어 둠)
- [ ] 11/13 벡터 DB 를 GCS 에 올리고 배포 (3번 "벡터 DB 올리기")
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
