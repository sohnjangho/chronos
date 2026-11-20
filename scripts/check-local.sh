#!/usr/bin/env bash
# 개발 중 검사(맥에서 직접). check.sh 와 같은 단계를 Docker 없이 돈다.
# 최종 점검과 PR 보고서는 check.sh(Docker)로 한다.
# 준비: backend/.venv (python3.13, pyproject 의존성), frontend/node_modules (npm ci).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="${ROOT}/backend/.venv/bin/python"

stage() {
  local name="$1"
  shift
  echo "==> ${name}"
  if "$@"; then
    echo "    통과: ${name}"
  else
    echo "    실패: ${name}" >&2
    exit 1
  fi
}

in_backend() { (cd "${ROOT}/backend" && "$@"); }
in_frontend() { (cd "${ROOT}/frontend" && "$@"); }

stage "비밀 검사" bash scripts/check_secrets.sh
stage "줄 수 검사" "${PY}" scripts/check_lines.py "${ROOT}"
stage "줄 수 검사 시험" "${PY}" -m pytest -q -p no:cacheprovider -p no:asyncio scripts/tests
stage "ruff check" in_backend "${PY}" -m ruff check .
stage "pytest" in_backend "${PY}" -m pytest -q
stage "eslint" in_frontend npm run lint
stage "tsc" in_frontend npm run typecheck
stage "vitest run" in_frontend npm test
stage "vite build" in_frontend npm run build

echo "모든 검사 통과"
