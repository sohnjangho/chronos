#!/usr/bin/env bash
# git 이 추적하는 파일에서 비밀값 흔적을 찾는다. 발견하면 종료 코드 1.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
found=0

env_files=$(git ls-files | grep -E '(^|/)\.env(\..+)?$' | grep -vE '(^|/)\.env\.example$')
if [ -n "$env_files" ]; then
  echo "오류: .env 파일이 추적되고 있다:"
  echo "$env_files"
  found=1
fi

if git grep -nIE 'sk-[A-Za-z0-9]{20,}'; then
  echo "오류: API 키(sk-…)로 보이는 문자열이 있다."
  found=1
fi

if git grep -nIiE "api[_-]?key[[:space:]]*[:=][[:space:]]*['\"][A-Za-z0-9]{16,}"; then
  echo "오류: api_key 값으로 보이는 문자열이 있다."
  found=1
fi

exit "$found"
