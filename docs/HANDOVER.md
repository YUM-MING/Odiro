# 인수인계 문서

> 주차가 끝나면 **아래 양식을 복사해 맨 위에 새 섹션으로 추가**하고 push 한다. 최신이 위.
> 다음 담당자는 자기 주차 시작 전에 이 문서 → [TEAM_ROLES.md](TEAM_ROLES.md) → [DATA_AND_API.md](DATA_AND_API.md) 순으로 읽는다.

---

## 양식 (복사해서 쓰기)

```markdown
## N주차 → N+1주차 인수인계 (담당: 이름, 기간: MM/DD ~ MM/DD)

### 1. 한 줄 요약
이번 주에 뭐가 "돌아가게" 됐는지 한 문장.

### 2. 완료한 것
- [x] 항목 (관련 파일/커밋)

### 3. 못 한 것 / 미뤄진 것 (다음 담당자가 이어받을 것)
- [ ] 항목 — 왜 못 했는지, 어디까지 했는지

### 4. 다음 담당자가 첫날 해야 할 것 (순서대로)
1. ...

### 5. 알아야 할 것 (함정·결정 사항)
- ...

### 6. 자원 위치
| 항목 | 위치 |
|---|---|
| 데이터 tgz | Drive 링크 |
| API 키 | 메신저 비공개 노트 |
| 배포 URL | ... |

### 7. 체크리스트 (인수인계 전 본인 확인)
- [ ] `main` 에 push 됐고 빌드 통과
- [ ] `.env`·데이터가 git 에 안 들어갔는지 `git status` 확인
- [ ] 데이터 tgz 업로드 + 링크 기입
- [ ] 다음 담당자에게 메신저로 알림
```

---

## 1주차 → 2주차 인수인계 (담당: YUM-MING, 기간: 11/04 ~ 11/11)

### 1. 한 줄 요약
**수도권 데이터(장소 1.9만 + 블로그 6.7만) → RAG → LangGraph 에이전트 → FastAPI(SSE) → React 플래너(지도)까지 전 과정이 로컬에서 돌아간다.**
"성수동 조용한 데이트" 를 넣으면 30~45초 뒤 카카오맵에 실존 확인된 장소 4~5곳과 동선이 찍히고, "3번째를 실내로 바꿔줘" 가 12초 안에 반영된다.
원래 1주차 범위(Phase 1)를 넘어 Phase 2(에이전트)·3(UI) 1차 구현까지 끝냈으므로 **2·3주차 역할을 아래 4번처럼 조정**했다.

### 2. 완료한 것
- [x] **API 키 10개 전부 발급·검증** (`python scripts/check_apis.py` 전부 OK). 네이버 검색 API 는 2026-07-31 이관으로 **NCP NAVER API HUB** 에서 발급(엔드포인트·헤더 다름, 코드 반영됨)
- [x] **데이터 (수도권: 서울 11·인천 28·경기 41)** — 커밋 `eab1cca`, `6cd88f6`
  - TourAPI 장소 메타 19,424건 (`lDongRegnCd` 법정동 코드 기준. 구 `areaCode` 는 1/8 만 나옴), 서울 상세(overview) 999건
  - 네이버 블로그 67,172건 (시군구 × 테마 11 × 100위까지), 타지역 글 필터(`off_region`), 광고 1차 플래그
  - gpt-4o-mini 라벨링 65,199건(태그 11종 + 광고 판정) → Chroma 인덱스 **63,347청크 / 675MB** (서울 19,117 · 인천 8,229 · 경기 36,001). `gs://odiro-where-data/vectorstore.tgz` 에 업로드
  - `odiro/data/ingest/*` 6개 모듈, 전부 재실행 안전·지역 인자(`--area`, `--all`)
- [x] **Tool 6개** (`odiro/tools/`): `rag_search`(태그·지역 필터), `search_place`(카카오 실존 검증·지오코딩), `get_route`(Mobility/Tmap + 직선거리 폴백), `get_sun_times`, `get_weather`, `summarize_reviews`(Tavily + LLM). 전부 diskcache + 8초 타임아웃 — 커밋 `c50419d`
- [x] **LangGraph** (`odiro/agent/`): 7 노드 + 수정 플라이휠(`modify`). 초안에 예비 후보를 같이 받아 검증 실패 자리를 메우고, 이름 유사도 + 카테고리 일치로 **할루시네이션 장소 0건** 보장. CLI `python -m odiro.agent.run "성수동" --edit "..."`
- [x] **FastAPI**: `POST /api/course`, `/course/start` + `GET /course/stream/{job}`(SSE 진행상태), `/course/edit(/start)`, `/moods`. 계약 문서 `docs/API_SCHEMA.md`
- [x] **프론트**: 랜딩 검색 카드 → 조건 빌더 → `/plan` (SSE 진행 사이드바, 채팅 마크다운, 카카오맵 번호 핀·동선·팝업, 장소별 바꾸기·빠른 수정·자유 수정, 공유, 목업 모드 `VITE_MOCK=1`). 로그인/회원가입은 **넣지 않기로 결정**해 제거
- [x] 시연 시나리오 3개 사전 캐시 스크립트 `scripts/warm_demo_cache.py` (성수동 데이트 / 가평 1박2일 자차 / 인천 송도 가족)
- [x] 자동 배포 워크플로 `.github/workflows/deploy.yml` (0주차 문서엔 있다고 돼 있었지만 실제론 없었음) — 활성화는 3번
- [x] 테스트 41개 (`pytest`, 네트워크 없음), ruff 통과, 프론트 lint·build 통과
- [x] 문서: 목표 **전국**, 1주차 수도권 → 나머지 14개 시도는 다음 주차가 `--all` 로. 브랜치 없이 `main` 직접 작업으로 규칙 변경. TourAPI 개발계정 절차(운영계정은 호출 이력 없으면 반려됨)

### 3. 못 한 것 / 미뤄진 것
- [x] ~~배포 활성화~~ — 자동 배포는 **이미 켜져 있었다** (0주차가 `setup_ci.sh` 는 실행했고 워크플로 파일만 안 올렸던 것). 11/11 부터 `main` push 마다 Cloud Run + Hosting 배포가 돈다 (https://github.com/YUM-MING/Odiro/actions). 벡터 DB 는 `gs://odiro-where-data/vectorstore.tgz` + Variable `VECTORSTORE_GCS_URI` 로 이미지에 포함.
- [x] **Cloud Run 환경변수(API 키)** — 11/11 등록 완료 (`/api/config-check` → `ready:true`). 키를 바꾸면 `python scripts/push_env_to_cloudrun.py` 재실행 (gcloud 로그인 필요). 비어 있으면 사이트의 `/api/config-check` 가 `ready:false` 이고 코스 생성이 503. 키를 바꾸면 다시 실행.
- [x] **Kakao 도메인 등록** — 11/11 완료, 배포 사이트에서 지도 표시 확인. 콘솔 메뉴는 "플랫폼 → Web" 이 아니라 **JavaScript SDK 도메인** (`http://localhost:5173`, `https://odiro-where.web.app`). 안 하면 지도 SDK 가 "domain mismatched" 로 거부돼 지도 패널만 비어 보인다 (코스 생성 자체는 됨).
- [ ] **⚠ 배포 서버 메모리 초과** — 11/11 라이브(2Gi)에서 코스 생성을 순서대로 5회 호출했더니 4회가 중간에 끊겼다 (성수동·가평 각 2회 실패, 인천 송도 1회 성공). Cloud Run 로그에 매번 `Memory limit of 2048 MiB exceeded` + 인스턴스 강제 종료. 동시 요청 3개는 전부 실패. 끊길 때 서버는 error 이벤트 없이 SSE 만 닫는다(프론트 표시는 미확인). 로컬 측정으로 벡터 검색만 약 1.1GB 를 잡는다. `get_vectorstore()` 를 캐시해도 메모리는 같았다(원인 아님). **조치**: 11/11 `deploy.yml` 의 `--memory 2Gi` → `4Gi` 로 올림. 비용은 무료 한도(월 36만 GiB·초) 안이면 0원, 넘으면 코스 1건당 약 0.4원 증가 수준(요금표 재확인 필요). 4Gi 로도 부족하면 인덱스를 줄이기(블로그 청크 수 축소, 임베딩 차원 축소) 또는 시연 3개 시나리오를 `scripts/warm_demo_cache.py` 캐시로만 응답. 확인: `gcloud logging read 'resource.labels.service_name="odiro-api" AND severity>=WARNING' --limit 20`
- [ ] **TourAPI 상세(overview)** — 개발계정 기능별 일 1,000건이라 서울 999건만. 매일 `python -m odiro.data.ingest.tour_api --no-meta` 한 번씩 (인천·경기 관광지/문화시설 우선). **운영계정 전환 신청**은 호출 이력이 생겼으니 지금 넣을 것 (data.go.kr → 해당 API → 변경 신청, 활용 URL 에 https://odiro-where.web.app)
- [ ] **나머지 14개 시도** (D6~D8) — `tour_api --all`, `naver_blog --all`, `labeling --all`, `build_index --all` 순서. 블로그 라벨링 비용은 1만 건당 약 1달러
- [ ] **품질** — 아직 손볼 곳: (a) 자차 모드 반경 30km 라 "송도" 요청에 계양구 장소가 섞임 → 동 단위 요청이면 반경 10km 로 줄이기 (b) 리뷰 요약이 '정보 부족' 으로 비는 비율 30~50% (c) 체류 시간이 LLM 기본값 60분으로 몰림 (d) 여행 모드 숙소 배치가 불안정 (e) 응답 시간 30~45초 → draft/compose 를 더 빠른 모델로 분리하거나 compose 를 스트리밍 (f) 수정 요청 "마지막 장소를 실내 놀이공간으로" 에 진행 표시는 "키즈카페 송도" 인데 실제 결과는 "송도카페거리" 로 들어감 (g) 비 예보(강수 100%)인데 야외인 송도센트럴파크가 "실내 공간" 으로 요약됨 (h) 수정 응답에서 날씨가 `available:false`·기온 없음으로 바뀜
- [ ] **프론트 실브라우저 검증** — 11/11 YUM-MING 이 배포 사이트에서 코스 생성·지도 표시까지 눌러 봄(정상). 로컬(`npm run dev` + 백엔드)과 서버가 끊겼을 때의 화면은 다음 담당자가 한 번 확인
- [ ] 발표용 그래프 이미지: `python -m odiro.agent.graph` 출력(Mermaid)을 https://mermaid.live 에서 PNG 로

### 4. 다음 담당자가 첫날 해야 할 것 (순서대로)
1. 이 문서 → `README.md` → `docs/API_SCHEMA.md` 읽기. `.env` 는 메신저 비공개 노트에서, 벡터 DB tgz 는 6번 Drive 링크에서 받아 `data/` 에 풀기
2. 로컬 세팅 후 `pytest`, `python scripts/check_apis.py`, `python -m odiro.agent.run "성수동"` 이 되는지 확인. 프론트 `npm run dev` 로 `/plan` 까지 눌러보기
3. 배포는 이미 켜져 있다 (`main` push → 자동 배포, API 키·카카오 도메인 등록 완료). 3번의 "배포 서버 메모리 초과" 가 4Gi 에서 재발하는지 로그로 확인할 것
4. `tour_api --no-meta` 하루 1회 돌리기 시작 + 운영계정 전환 신청
5. 역할 재조정 (TEAM_ROLES.md 에 반영함): **2주차 = 전국 데이터 확장 + 에이전트 품질(위 3번 '품질' 항목) + 테스트**, **3주차 = UI 다듬기 + 안정화·시연 영상**

### 5. 알아야 할 것 (함정·결정 사항)
- **TourAPI 키는 Decoding 키.** Encoding 키(`%2B` 포함)를 넣으면 `SERVICE_KEY_IS_NOT_REGISTERED`. 코드가 `%` 들어간 키를 거부한다.
- **네이버 검색 API 는 NCP** (`naverapihub.apigw.ntruss.com`, 헤더 `X-NCP-APIGW-API-KEY-ID/KEY`). developers.naver.com 키는 신규 발급 불가.
- **Kakao Local 403 "disabled OPEN_MAP_AND_LOCAL"** 이면 카카오 디벨로퍼스 앱에서 "카카오맵" 활성화 ON.
- **Tmap 403 INVALID_API_KEY** 면 openapi.sk.com 프로젝트에 TMAP API 상품이 안 붙은 것.
- httpx 는 INFO 로그에 요청 URL 전체(서비스 키 포함)를 찍는다 → 로깅 설정에서 꺼 두었다. 새 스크립트 만들 때 주의.
- 라벨링·임베딩·코스 생성 비용은 전부 `OPENAI_API_KEY` 계정에서 나간다. 1주차 총 약 4~6달러. 코스 1건 ≈ 10~20원.
- `rag_search` 지역 해석은 시군구 이름 기준(캐시 `cache/ingest_state/sigungu_*.json`). "송도" 같은 동 이름은 시도까지만 잡히고, 좌표 중심은 카카오 주소 검색으로 따로 잡는다.
- 프론트는 SSE 때문에 Cloud Run 을 **직접** 호출한다(`VITE_API_URL`). Hosting rewrite 는 응답을 버퍼링해 진행 표시가 안 된다. CORS 허용 도메인은 `odiro/config.py`.
- 같은 요청은 7일 캐시(`cache/tools`) → 시연 리허설 때 결과가 안 바뀌면 `--no-cache` 또는 `cache/tools` 삭제.
- 데이터 라벨에 **타지역 글**("연수구" 쿼리에 대전 글)이 섞여 들어오던 문제는 `off_region` 으로 걸러냈고 인덱스에서도 삭제했다. 전국 확장 때 `OTHER_REGION_WORDS` 를 해당 시도에 맞게 손볼 것.

### 6. 자원 위치
| 항목 | 위치 |
|---|---|
| 서비스 | https://odiro-where.web.app (플래너 배포됨. 백엔드 메모리 4Gi, 경과는 3번 참고) |
| 백엔드 직접 URL | https://odiro-api-80160454962.asia-northeast3.run.app |
| GitHub | https://github.com/YUM-MING/Odiro (`main` 직접 작업) |
| 데이터 tgz | 벡터 DB: `gs://odiro-where-data/vectorstore.tgz` (GCP 콘솔 Storage 에서 다운로드, 약 600MB) · 원본+상태: `odiro-data-20261111.tgz` → **Drive 링크: (업로드 후 기입)**. 로컬 복원: `tar xzf vectorstore.tgz -C data/` |
| API 키 | 메신저 비공개 노트 (`.env` 완성본) |
| 시연 캐시 | `cache/demo/*.json` (`scripts/warm_demo_cache.py --date <시연일>` 로 생성) |
| 그래프 다이어그램 | `python -m odiro.agent.graph` |

### 7. 체크리스트
- [x] `main` 에 push 됐고 빌드 통과 (`pytest` 41, ruff, `npm run lint`, `npm run build`)
- [x] `.env`·데이터가 git 에 안 들어갔는지 확인
- [ ] 데이터 tgz 업로드 + 링크 기입
- [ ] 다음 담당자에게 메신저로 알림

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
