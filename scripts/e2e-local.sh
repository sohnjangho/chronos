#!/usr/bin/env bash
# 화면 끝에서 끝까지 시험(Playwright, FHD)을 맥에서 직접 돈다. Docker 를 쓰지 않는다.
#
# - 임시 자료 폴더(mktemp)에 씨앗 일정(python -m app.seed demo)을 넣고, 가짜 LLM(CHRONOS_FAKE_LLM=1)으로
#   백엔드를 띄운다. Liner 를 부르지 않는다. ~/projects/chronos/data 와 PM 앱(8210/5600)은 건드리지 않는다.
# - 포트: 백엔드 E2E_API_PORT(기본 8310), 화면 E2E_WEB_PORT(기본 5700).
# - 단계 화면은 E2E_SHOTS_DIR(없으면 새 임시 폴더, 끝에 경로를 알림)에 저장된다. 커밋한 화면을 다시 찍을 때만
#   E2E_SHOTS_DIR="$PWD/docs/demo/shots" 를 준다. 끝나면 서버를 끄고 자료 임시 폴더를 지운다.
# - 브라우저는 frontend/.playwright-browsers 에만 둔다(맥 전체 캐시 ~/Library/Caches/ms-playwright 를 건드리지 않음).
# 준비: backend/.venv, frontend/node_modules, 크로미움 한 번:
#   cd frontend && PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" PLAYWRIGHT_SKIP_BROWSER_GC=1 npx playwright install chromium
# 쓰는 법: bash scripts/e2e-local.sh [playwright test 인자…]
set -euo pipefail
CALLER_PWD="$(pwd)"
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
export PLAYWRIGHT_BROWSERS_PATH="${ROOT}/frontend/.playwright-browsers"
export PLAYWRIGHT_SKIP_BROWSER_GC=1
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
# 뜻 검색(Qdrant) 끔: 일꾼이 PM 앱의 Qdrant(127.0.0.1:6333)를 건드리지 않게 — 화면 시험은 낱말 검색만
export CHRONOS_QDRANT_URL=""

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

echo "==> 백엔드 띄우기 (127.0.0.1:${API_PORT}) — 시험 전용 감싸개: 내 컴퓨터 밖 연결은 막고 막은 호스트를 적는다"
# tests/e2e_server.py 는 앱을 그대로 띄우되 127.0.0.0/8·localhost 밖으로의 연결·이름 풀이를 막고, 막을 때마다 한 줄을
# CHRONOS_E2E_REFUSED_LOG 에 적는다. 화면 시험(contacts.spec.ts)은 끝에 그 파일이 비었는지 본다.
export CHRONOS_E2E_REFUSED_LOG="${WORK}/refused-hosts.log"
: >"${CHRONOS_E2E_REFUSED_LOG}"
(cd "${ROOT}/backend" && exec "${PY}" -m tests.e2e_server --host 127.0.0.1 --port "${API_PORT}") \
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

SHOTS="${E2E_SHOTS_DIR:-}"
if [ -z "${SHOTS}" ]; then
  SHOTS="$(mktemp -d "${TMPDIR:-/tmp}"/chronos-e2e-shots.XXXXXX)"
elif [ "${SHOTS#/}" = "${SHOTS}" ]; then
  SHOTS="${CALLER_PWD}/${SHOTS}"  # 상대 경로는 부른 곳 기준
fi

echo "==> Playwright (1920×1080)"
cd "${ROOT}/frontend"
E2E_SHOTS_DIR="${SHOTS}" E2E_BASE_URL="http://127.0.0.1:${WEB_PORT}" E2E_LOGIN_ID="${CHRONOS_ADMIN_ID}" \
  E2E_PASSWORD="${CHRONOS_ADMIN_PASSWORD}" E2E_OUTPUT_DIR="${WORK}/playwright" \
  npx playwright test "$@"
if [ -s "${CHRONOS_E2E_REFUSED_LOG}" ]; then
  echo "알림: 시험 서버가 내 컴퓨터 밖 연결을 막았습니다:" >&2
  cat "${CHRONOS_E2E_REFUSED_LOG}" >&2
fi
echo "끝에서 끝까지 시험 통과 — 화면: ${SHOTS}"
