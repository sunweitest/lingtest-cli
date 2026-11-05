#!/usr/bin/env bash
# Verify that a git ref of this repository installs and runs as a standalone CLI.
#
#   scripts/verify-git-install.sh                       # origin/main
#   scripts/verify-git-install.sh <url> <ref>           # specific remote + ref/sha
#
# Exits non-zero if install, version check, or case generation/execution fails.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_URL="${1:-$(git -C "$REPO_ROOT" config --get remote.origin.url)}"
REF="${2:-main}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "== installing lingtest-cli from ${REPO_URL}@${REF}"
uv venv --quiet "$WORK/venv"
VIRTUAL_ENV="$WORK/venv" uv pip install --quiet "lingtest-cli[tui] @ git+${REPO_URL}@${REF}"

echo "== version"
"$WORK/venv/bin/lingtest" --version

echo "== providers (missing keys are fine)"
"$WORK/venv/bin/lingtest" providers

echo "== installed source"
"$WORK/venv/bin/python" -c "
import importlib.metadata as m
print(m.distribution('lingtest-cli').read_text('direct_url.json'))
"

echo "== deterministic generate + run smoke (no server on :9, failures expected)"
cp "$REPO_ROOT/examples/openapi.yaml" "$WORK/openapi.yaml"
cd "$WORK"
"$WORK/venv/bin/lingtest" generate openapi.yaml --strategy deterministic -o cases.json
"$WORK/venv/bin/lingtest" run cases.json --base-url http://127.0.0.1:9 -o report.json --timeout 2 || true
test -s report.json

echo "== OK: ${REPO_URL}@${REF} installs and runs"
