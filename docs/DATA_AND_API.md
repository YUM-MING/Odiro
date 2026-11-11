# 데이터 · API 목록

> 뭘 발급받아야 하고, 뭘 모아야 하는지 한 장에 정리. 담당 주차는 [TEAM_ROLES.md](TEAM_ROLES.md) 기준.
> 키 값은 **절대 이 문서나 git 에 쓰지 않는다.** 로컬은 `.env`, 배포는 Cloud Run 환경변수에만 넣는다.

## 1. API 키 (총 10개, 필수 9 + 선택 1)

| # | API | 용도 | 환경변수 | 발급 | 무료 한도 | 발급 난이도 | 담당 |
|---|---|---|---|---|---|---|---|
| 1 | **OpenAI** (또는 Anthropic) | LLM 코스 생성·라벨링·임베딩 | `OPENAI_API_KEY` | https://platform.openai.com/api-keys | 유료 (gpt-4o-mini 기준 코스 1건 ≈ 10~30원) | 쉬움, 카드 필요 | 1주차 |
| 2 | **Kakao Local** (REST) | 장소 검색·좌표·실존 검증 | `KAKAO_REST_API_KEY` | https://developers.kakao.com → 내 애플리케이션 → 앱 키 | 일 30만 회 | 쉬움 | 1주차 |
| 3 | **Kakao Map JS** | 프론트 지도 표시 | `KAKAO_JS_API_KEY` | 2번과 같은 앱의 JavaScript 키. **플랫폼 → Web → 사이트 도메인에 `https://odiro-where.web.app`, `http://localhost:5173` 등록 필수** | 무료 | 쉬움 | 1주차 |
| 4 | **Kakao Mobility** (자차 길찾기) | 자동차 이동시간·경로 | `KAKAO_MOBILITY_API_KEY` | https://developers.kakaomobility.com → 앱 등록 (카카오디벨로퍼스와 **별도** 사이트) | 일 1만 회 | 보통 | 1주차 |
| 5 | **Tmap** (보행자 길찾기) | 뚜벅이 이동시간·경로 | `TMAP_APP_KEY` | https://openapi.sk.com → 앱 생성 → appKey | 일 1만 회 | 보통 | 1주차 |
| 6 | **TourAPI 4.0** (한국관광공사) | 전국 장소 메타데이터 대량 수집 | `TOUR_API_KEY` | https://www.data.go.kr → "한국관광공사_국문 관광정보 서비스_GW" 활용신청 → **일반 인증키(Decoding)** | **개발계정** 기능별 일 1,000건 (자동승인, 즉시). 운영계정은 **호출 이력 없으면 반려**되므로 개발계정으로 수집해 이력을 쌓은 뒤 "운영계정 전환 신청" (심의 영업일 2~7일) | 보통 (개발계정) / 느림 (운영 전환) | 1주차 발급 · 1주차 말 운영 전환 신청 |
| 7 | **네이버 검색 API** (블로그) | 큐레이션 글 수집 (RAG 원문) | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | **네이버 클라우드 플랫폼** https://console.ncloud.com → Services → Application Services → **NAVER API HUB** → Application 등록(검색 API 체크) → 인증 정보. 2026-07-31 이관으로 developers.naver.com 에서는 신규 발급 불가. 엔드포인트 `https://naverapihub.apigw.ntruss.com/search/v1/blog`, 헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY` | 일 25,000회 (한시 무료) | 쉬움 (NCP 가입·결제수단 등록 필요) | 1주차 |
| 8 | **Tavily** | 실시간 웹검색 (팝업·휴무·핫플) | `TAVILY_API_KEY` | https://tavily.com | 월 1,000회 | 쉬움 | 2주차 |
| 9 | **OpenWeather** | 날씨·강수확률 → 실내 전환 | `OPENWEATHER_API_KEY` | https://openweathermap.org/api → Current + 5 day forecast | 분 60회 / 일 100만 | 쉬움 (활성화까지 ~2시간) | 2주차 |
| 10 | 기상청 단기예보 (선택) | OpenWeather 대체 | `KMA_API_KEY` | data.go.kr "기상청_단기예보 조회서비스" | 일 10,000건 | 보통 | 생략 가능 |

- 일출·일몰은 `astral` 라이브러리로 오프라인 계산 → 키 불필요.
- 점검 방법: `.env` 채우고 `python scripts/check_apis.py` → 키마다 `OK / FAIL / SKIP` 출력.
- **발급 순서 추천**: 6(TourAPI, 승인 대기) → 2·3·4(Kakao) → 7(네이버) → 1(OpenAI) → 5(Tmap) → 8·9.

### 키를 넣는 곳

| 환경 | 위치 | 방법 |
|---|---|---|
| 로컬 개발 | 프로젝트 루트 `.env` | `.env.example` 복사해서 채움 (git 제외됨) |
| 배포 (Cloud Run) | GCP 콘솔 → Cloud Run → `odiro-api` → **수정 및 새 버전 배포** → 변수 및 보안 비밀 | 변수 이름은 `.env.example` 과 동일. 저장하면 새 버전 자동 배포 |
| 프론트 (Kakao JS 키) | 백엔드 `/api/public-config` 가 내려줌 | 프론트 `.env` 에 넣지 않는다 (번들에 노출되므로 도메인 제한으로만 보호) |

### 팀원 계정 공유

- API 키는 **1명이 발급해 팀 메신저의 비공개 노트로 공유** (각자 `.env` 에 붙여넣기). git·문서·공개 채팅 금지.
- Kakao·TourAPI 처럼 콘솔에서 도메인·쿼터를 만지는 건 발급자가 담당.

## 2. 데이터 목록

### 2-1. 수집해야 하는 데이터

| # | 데이터 | 소스 | 규모 | 용도 | 산출물 경로 | 담당 |
|---|---|---|---|---|---|---|
| D1 | **수도권 장소 메타** (법정동 시도코드 서울 11 · 인천 28 · 경기 41) | TourAPI `areaBasedList2` (`lDongRegnCd`, `numOfRows=1000`) | **실측 19,424건** (서울 8,008 / 인천 1,987 / 경기 9,429), 호출 48회 | 코스 후보 풀 (최우선) | `data/raw/tour/area_{시도코드}.jsonl` | 1주차 ✅ |
| D2 | **수도권 장소 상세** (overview) | TourAPI `detailCommon2` | 개발계정 기능별 일 1,000건 → 관광지→문화→음식점 순으로 매일 이어서. **11/11 기준 서울 999건** | 장소 설명 임베딩 | `data/raw/tour/detail_{시도코드}.jsonl` | 1주차 (매일 1회 실행) |
| D3 | **수도권 블로그 큐레이션 글** | 네이버 블로그 검색 (NCP API HUB) | 시군구 × 테마 11 × 상위 100건 → **실측 67,172건** (서울 18,442 / 인천 9,053 / 경기 39,677), 쿼리 ~2,000회 (`--start 31 --per-query 70` 로 31~100위 추가). 타지역 글 ~930건은 `off_region` 으로 제외 | RAG 원문 (분위기) | `data/raw/blog/area_{시도코드}.jsonl` | 1주차 ✅ |
| D4 | **분위기 태그 라벨링** (D2+D3) | gpt-4o-mini Structured Output, 10건 묶음 × 8 스레드 | **실측 65,199건**, 광고 판정 ~300건, 약 5달러 | 메타데이터 필터 | `data/raw/labeled/area_{시도코드}.jsonl` | 1주차 ✅ |
| D5 | **벡터 인덱스** (D4) | text-embedding-3-small + Chroma | **실측 63,347청크 (서울 19,117 / 인천 8,229 / 경기 36,001), 675MB** → Cloud Run 메모리 2Gi 로 배포 중 (부족 — 코스 생성 중 메모리 초과 잦음, HANDOVER 3번) | `rag_search` Tool | `data/vectorstore/` (git 제외, `gs://odiro-where-data/vectorstore.tgz` + Drive) | 1주차 ✅ |
| D6 | **나머지 14개 시도 장소 메타** | TourAPI `areaBasedList2` | 4~5만 건, 호출 100회 미만 | "전국 어디를 입력해도 동작" 보장 | `data/raw/tour/area_{시도코드}.jsonl` | **2주차** |
| D7 | **나머지 시도 블로그 큐레이션 글** | 네이버 블로그 검색 | 163 시군구 × 테마 10 ≈ 1,630 쿼리 | 전국 RAG | `data/raw/blog/area_{시도코드}.jsonl` | **2주차** (스크립트 돌려두고 다른 작업) |
| D8 | **나머지 시도 라벨링 + 인덱스 확장** | LLM + Chroma | 5~10만 건, 15~30달러 → **예산 보고 샘플링** | 전국 RAG 품질 | `data/vectorstore/` | 2주차 (시간 남으면), 아니면 3주차 |
| D9 | **시연 시나리오 캐시** | 완성된 파이프라인 실행 결과 | 3개 시나리오 (성수동 / 양평·가평 / 인천 송도) | 시연 안정성 (네트워크 죽어도 동작) | `cache/demo/*.json` | 3주차 |

- **지역 분담**: 서비스 목표는 전국. 1주차(YUM-MING)가 수도권(서울·인천·경기)을 D1~D5 까지 끝내면 Phase 1 완료. 나머지 14개 시도(D6~D8)는 양이 커서 **2주차가 같은 스크립트를 `--all` 로 백그라운드로 돌리면서** 에이전트 작업을 병행한다. 파일명은 시도코드 기준으로 통일해 두 사람의 산출물이 그대로 합쳐지게 한다.
- TourAPI 상세(D2·D6 상세)는 전수 호출이 비싸므로 **코스 생성 시 후보 장소만 지연 호출 + diskcache** 전략을 기본으로 하고, 사전 수집은 우선순위 상위(관광지·음식점·카페 중 블로그 언급 많은 곳)만.
- 수집 스크립트 위치: `odiro/data/ingest/` (`tour_api.py`, `naver_blog.py`, `labeling.py`, `build_index.py` — 1주차가 만든다).

### 2-2. 데이터 공유 방법 (git 에 안 올라감)

- `data/raw/`, `data/vectorstore/`, `cache/` 는 `.gitignore` 되어 있음.
- 주차가 바뀔 때 `tar czf odiro-data-YYYYMMDD.tgz data/raw data/vectorstore` 로 묶어 **Google Drive 공유 폴더**에 올리고, 인수인계 문서에 링크를 적는다.
- Cloud Run 컨테이너는 상태가 없으므로 벡터 DB 는 **이미지에 포함**시키거나(수백 MB 이하면 OK) GCS 버킷에서 기동 시 내려받는다 → 3주차가 결정.

### 2-3. 하지 않는 것

- 인스타그램·캐치테이블·테이블링 **직접 크롤링 금지** (약관 위반 + 차단 → 시연 불안정).
- "웨이팅 적은" 같은 정보는 블로그 텍스트에서 LLM 태그로 추출, 예약은 링크 아웃.

## 3. 분위기 태그 체계 (라벨링 기준)

`감성/조용한` · `힙한/트렌디` · `뷰맛집/일몰` · `레트로` · `자연/산책` · `실내(비오는날)` · `액티비티` · `사진맛집` · `웨이팅적은` · `아이동반` · `반려동물` · `광고성(제외용)`
