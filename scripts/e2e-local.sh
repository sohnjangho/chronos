#!/usr/bin/env bash
# 화면 끝에서 끝까지 시험(Playwright, FHD)을 맥에서 직접 돈다. Docker 를 쓰지 않는다.
#
# - 임시 자료 폴더(mktemp)에 씨앗 일정(python -m app.seed demo)을 넣고, 가짜 LLM(CHRONOS_FAKE_LLM=1)으로
#   백엔드를 띄운다. Liner 를 부르지 않는다. ~/projects/chronos/data 와 PM 앱(8210/5600)은 건드리지 않는다.
# - 포트: 백엔드 E2E_API_PORT(기본 8310), 화면 E2E_WEB_PORT(기본 5700).
# - 단계 화면은 docs/demo/shots/ 에 저장된다. 끝나면 서버를 끄고 임시 폴더를 지운다.
# 준비: backend/.venv, frontend/node_modules, 크로미움(cd frontend && npx playwright install chromium).
# 쓰는 법: bash scripts/e2e-local.sh [playwright test 인자…]
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="${ROOT}/backend/.venv/bin/python"
API_PORT="${E2E_API_PORT:-8310}"
WEB_PORT="${E2E_WEB_PORT:-5700}"

for port in "${API_PORT}" "${WEB_PORT}"; do
  if [ "${port}" = 8210 ] || [ "${port}" = 5600 ]; then
    echo "오류: ${port} 는 PM 앱 포트입니다. 다른 포트를 쓰세요." >&2
    exit 2
  fi
  if lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "오류: ${port} 포트를 이미 쓰고 있습니다." >&2
    exit 2
  fi
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}"/chronos-e2e.XXXXXX)"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid}" ] && kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "${WORK}"
}
trap cleanup EXIT

# 시험 전용 값(가상). 실제 .env 를 읽지 않는다.
export CHRONOS_DATA_DIR="${WORK}/data"
export CHRONOS_SECRET_KEY="e2e-$(openssl rand -hex 24)"
export CHRONOS_ADMIN_ID="demo-admin"
export CHRONOS_ADMIN_PASSWORD="demo-pass-e2e"
export CHRONOS_FAKE_LLM=1

echo "==> 씨앗 일정 넣기 (${CHRONOS_DATA_DIR})"
(cd "${ROOT}/backend" && "${PY}" -m app.seed demo)

echo "==> 가짜 LLM 연결 한 줄 넣기(임시 DB, 가짜 키 — 요청은 app.llm.fake 가 받는다)"
(cd "${ROOT}/backend" && "${PY}" - <<'PY'
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.security.crypto import encrypt
from app.store.tables import LlmConnection

engine = create_engine(f"sqlite:///{Settings().data_dir / 'chronos.db'}")
with Session(engine) as session:
    session.add(LlmConnection(
        name="시연용 가짜 연결", provider="liner", base_url="https://platform.liner.com/api/v1",
        secret_ciphertext=encrypt("fake-e2e-0000"), secret_last4="0000", is_default=True, status="ok",
    ))
    session.commit()
engine.dispose()
PY
)

echo "==> 백엔드 띄우기 (127.0.0.1:${API_PORT})"
(cd "${ROOT}/backend" && exec "${PY}" -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT}") \
  >"${WORK}/backend.log" 2>&1 &
PIDS+=($!)

echo "==> 화면 띄우기 (127.0.0.1:${WEB_PORT})"
(cd "${ROOT}/frontend" && CHRONOS_API_URL="http://127.0.0.1:${API_PORT}" \
  exec npx vite --host 127.0.0.1 --port "${WEB_PORT}" --strictPort) >"${WORK}/frontend.log" 2>&1 &
PIDS+=($!)

wait_for() {
  local url="$1" name="$2"
  for _ in $(seq 1 60); do
    if curl -fs -o /dev/null "${url}"; then return 0; fi
    sleep 1
  done
  echo "오류: ${name} 가 뜨지 않았습니다." >&2
  cat "${WORK}/backend.log" "${WORK}/frontend.log" >&2
  return 1
}
wait_for "http://127.0.0.1:${API_PORT}/api/health" "백엔드"
wait_for "http://127.0.0.1:${WEB_PORT}/" "화면"

if ! grep -q "CHRONOS_FAKE_LLM=1" "${WORK}/backend.log"; then
  echo "오류: 백엔드 로그에 가짜 LLM 경고가 없습니다(가짜가 켜지지 않았을 수 있음)." >&2
  exit 1
fi
echo "    가짜 LLM 경고 확인: $(grep -m1 "CHRONOS_FAKE_LLM=1" "${WORK}/backend.log")"

echo "==> Playwright (1920×1080)"
cd "${ROOT}/frontend"
E2E_BASE_URL="http://127.0.0.1:${WEB_PORT}" E2E_LOGIN_ID="${CHRONOS_ADMIN_ID}" \
  E2E_PASSWORD="${CHRONOS_ADMIN_PASSWORD}" E2E_OUTPUT_DIR="${WORK}/playwright" \
  npx playwright test "$@"
echo "끝에서 끝까지 시험 통과 — 화면: docs/demo/shots/"
