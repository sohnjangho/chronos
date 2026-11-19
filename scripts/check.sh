#!/usr/bin/env bash
# 전체 검사. 단계마다 한 줄씩 알리고, 첫 실패에서 멈춘다.
# 비밀 검사만 호스트에서(git 필요), 나머지는 Docker 안에서 돈다.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"

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

backend() { docker compose run --rm -T backend "$@"; }
frontend() { docker compose run --rm -T frontend "$@"; }

stage "이미지 준비" docker compose build -q
stage "비밀 검사" bash scripts/check_secrets.sh
stage "줄 수 검사" docker compose run --rm -T -v "${ROOT}:/repo:ro" backend \
  python /repo/scripts/check_lines.py /repo
stage "줄 수 검사 시험" docker compose run --rm -T -v "${ROOT}/scripts:/scripts:ro" backend \
  pytest -q -p no:cacheprovider /scripts/tests
stage "ruff check" backend ruff check .
stage "pytest" backend pytest -q
stage "eslint" frontend npm run lint
stage "vitest run" frontend npm test
stage "vite build" frontend npm run build

echo "모든 검사 통과"
