#!/usr/bin/env bash
# GitHub Actions 자동 배포 활성화 (1회만). Cloud Shell 에서 `bash scripts/setup_ci.sh`
# 하는 일: 배포용 서비스 계정 생성 → 권한 부여 → 키 발급 → GitHub secret/variable 등록 → 키 파일 삭제
set -euo pipefail

PROJECT=odiro-where
SA_NAME=github-deploy
SA="$SA_NAME@$PROJECT.iam.gserviceaccount.com"
REPO=YUM-MING/Odiro

command -v gh >/dev/null || { echo "gh CLI 가 필요합니다"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "먼저 gh auth login"; exit 1; }

echo "1) 서비스 계정 생성"
gcloud iam service-accounts create "$SA_NAME" --display-name="GitHub Actions deploy" --project "$PROJECT" 2>/dev/null || echo "   (이미 있음)"

echo "2) 권한 부여"
for ROLE in roles/run.admin roles/iam.serviceAccountUser roles/cloudbuild.builds.editor \
            roles/storage.admin roles/artifactregistry.writer roles/serviceusage.serviceUsageConsumer \
            roles/firebasehosting.admin roles/viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$ROLE" --quiet >/dev/null
  echo "   $ROLE"
done

echo "3) 키 발급 → GitHub secret 등록"
KEY=$(mktemp)
gcloud iam service-accounts keys create "$KEY" --iam-account="$SA" --project "$PROJECT" --quiet
gh secret set GCP_SA_KEY --repo "$REPO" < "$KEY"
rm -f "$KEY"

echo "4) 워크플로 활성화"
gh variable set CI_ENABLED --repo "$REPO" --body true

echo
echo "완료. 이제 main 에 push 하면 자동 배포됩니다: https://github.com/$REPO/actions"
