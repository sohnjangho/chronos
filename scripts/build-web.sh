#!/usr/bin/env bash
# 화면을 빌드해 backend/app/web 에 넣는다 — chronos 명령(uvx 한 줄 설치)이 Node 없이 이 사본을 내준다.
# 화면(frontend/src)을 바꾼 뒤 다시 돌려 커밋한다. 개발·Docker 는 이 사본을 쓰지 않는다(vite 가 화면을 낸다).
# 준비: frontend/node_modules (npm ci).
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$(pwd)/backend/app/web"

(cd frontend && npx vite build --outDir "$OUT" --emptyOutDir)
# 커밋하지 않는 로컬 파일(.gitignore)과 소스 맵은 싣지 않는다
rm -f "$OUT"/media/login-bg-prev-*.mp4
find "$OUT" -name '*.map' -delete
du -sh "$OUT"
