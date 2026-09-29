#!/usr/bin/env bash
# Laptop only. Runs validate.py — no gh, no gcloud, no live repos.
#
# Usage: ./verify-jobs-local.sh
# Arguments: none.
# Exit codes: whatever validate.py's unittest run exits with (0 pass, 1 fail).
set -euo pipefail
cd "$(dirname "$0")"
python3 validate.py
