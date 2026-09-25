#!/usr/bin/env bash
# Checks .gitmodules doesn't track a moving branch and nothing floats past the pin.

set -euo pipefail

ROOT="${1:-.}"
die() { echo "error: $*" >&2; exit 1; }

GITMODULES="${ROOT}/.gitmodules"
[ -f "$GITMODULES" ] || die "no .gitmodules under ${ROOT}"

if grep -E '^[[:space:]]*branch[[:space:]]*=' "$GITMODULES" >/dev/null; then
  die ".gitmodules still has 'branch =' lines — those float. Remove them so gitlinks are the pin."
fi

if grep -R --include='*.yml' --include='*.yaml' --include='*.sh' -n 'submodule update --remote' "$ROOT" >/dev/null 2>&1; then
  die "found 'git submodule update --remote' — that floats past the gitlink SHA"
fi

echo "ok: .gitmodules has no branch= pins; no --remote submodule updates."
echo "To materialize the recorded SHAs: git submodule update --init"
echo "Cloud Build uses ci/checkout-gitlinks.py instead of gitSource revision: main."
