#!/usr/bin/env bash
# developer-connect-setup.sh — prints the 4c browser + link commands.
# Does not run gcloud. Creating a Developer Connect GitHub connection needs a
# one-time URL approval in a browser; that cannot be scripted.

set -euo pipefail

REGION="asia-south1"
REPOS=(sujho text-agent user-service whatsapp-adapter admin document-worker redirect-service knowledge-store sujho-ops-mcp)

echo "This script only prints commands. Run them yourself after the browser step."
echo

for PROJECT in sujho-dev sujho-preprod; do
  echo "=== $PROJECT ==="
  echo "Step 1 (manual): run this, then open the printed URL and authorize:"
  echo "  gcloud builds connections create github sujho-github-dc \\"
  echo "    --project=$PROJECT --region=$REGION"
  echo
  echo "Step 2, once authorized — verify it's COMPLETE:"
  echo "  gcloud builds connections describe sujho-github-dc \\"
  echo "    --project=$PROJECT --region=$REGION"
  echo
  echo "Step 3 — link repos to the now-authorized connection:"
  for REPO in "${REPOS[@]}"; do
    echo "  gcloud builds repositories create ${REPO} \\"
    echo "    --remote-uri=https://github.com/Sujho/${REPO}.git \\"
    echo "    --connection=sujho-github-dc --region=$REGION --project=$PROJECT"
  done
  echo
done

echo "Prod already uses connection sujho-github-dc-org in sujho-478914."
echo "Do not recreate that from here. New projects use sujho-github-dc."
