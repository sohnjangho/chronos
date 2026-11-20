#!/usr/bin/env bash
# macOS 로컬 Qdrant 실행 스크립트 (Docker 없이 직접 실행, 버전 고정).
# 저장 경로: <저장소>/data/qdrant (또는 CHRONOS_DATA_DIR/qdrant)
# 사용법: bash scripts/qdrant-local.sh
set -euo pipefail

QDRANT_VERSION="v1.13.4"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${CHRONOS_DATA_DIR:-$ROOT/data}/qdrant"
BIN_DIR="$ROOT/data/bin"
BIN="$BIN_DIR/qdrant-$QDRANT_VERSION"

mkdir -p "$DATA_DIR" "$BIN_DIR"

if [[ ! -x "$BIN" ]]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    arm64)  TARGET="aarch64-apple-darwin" ;;
    x86_64) TARGET="x86_64-apple-darwin" ;;
    *) echo "지원하지 않는 아키텍처: $ARCH" >&2; exit 1 ;;
  esac
  URL="https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-${TARGET}.tar.gz"
  echo "Qdrant ${QDRANT_VERSION} (${TARGET}) 내려받는 중..."
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "$URL" -o "$TMP/qdrant.tar.gz"
  tar -xzf "$TMP/qdrant.tar.gz" -C "$TMP"
  mv "$TMP/qdrant" "$BIN"
  chmod +x "$BIN"
fi

echo "Qdrant 시작 (http://127.0.0.1:6333, storage: $DATA_DIR)"
export QDRANT__STORAGE__STORAGE_PATH="$DATA_DIR"
export QDRANT__SERVICE__HOST="127.0.0.1"
export QDRANT__SERVICE__HTTP_PORT="6333"
exec "$BIN"
