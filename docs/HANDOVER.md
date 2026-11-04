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
