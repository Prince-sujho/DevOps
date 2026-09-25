#!/usr/bin/env bash
# Prints the browser + link commands for sujho-preprod's Developer Connect connection.

set -euo pipefail

REGION="asia-south1"
CONNECTION="sujho-github-dc-org"
PROJECT="sujho-preprod"
REPOS=(sujho text-agent user-service whatsapp-adapter admin document-worker redirect-service knowledge-store sujho-ops-mcp)

echo "prints commands only — run them yourself after the browser auth step"
echo
echo "=== $PROJECT ==="
echo "1. run this, open the printed URL, authorize:"
echo "  gcloud builds connections create github $CONNECTION \\"
echo "    --project=$PROJECT --region=$REGION"
echo
echo "2. once authorized, verify COMPLETE:"
echo "  gcloud builds connections describe $CONNECTION \\"
echo "    --project=$PROJECT --region=$REGION"
echo
echo "3. link repos:"
for REPO in "${REPOS[@]}"; do
  echo "  gcloud builds repositories create ${REPO} \\"
  echo "    --remote-uri=https://github.com/Sujho/${REPO}.git \\"
  echo "    --connection=$CONNECTION --region=$REGION --project=$PROJECT"
done
echo
echo "sujho-478914 needs no changes — it never fetches source"
