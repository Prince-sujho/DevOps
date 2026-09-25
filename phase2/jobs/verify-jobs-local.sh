#!/usr/bin/env bash
# Laptop only. Runs validate.py — no gh, no gcloud, no live repos.
set -euo pipefail
cd "$(dirname "$0")"
python3 validate.py
