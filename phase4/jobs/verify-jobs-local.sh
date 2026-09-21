#!/usr/bin/env bash
# Laptop only. Regenerates the two workflow files and runs validate.py.
# No gh. No gcloud. No GitHub. No live repos.
set -euo pipefail
cd "$(dirname "$0")"
python3 generate_job_workflow.py
python3 validate.py
