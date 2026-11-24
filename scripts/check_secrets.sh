#!/usr/bin/env bash
# git 이 추적하는 파일에서 비밀값 흔적을 찾는다.
# 종료 코드: 0 = 없음, 1 = 발견, 2 = git 오류(검사를 못 했으니 실패로 본다).
set -uo pipefail

fail_git() {
  echo "오류: $1 — 비밀 검사를 하지 못했다." >&2
  exit 2
}

top=$(git rev-parse --show-toplevel) || fail_git "git 저장소가 아니다"
cd "$top" || fail_git "저장소 루트로 갈 수 없다"
tracked=$(git ls-files) || fail_git "git ls-files 실패"
found=0

env_files=$(printf '%s\n' "$tracked" | grep -E '(^|/)\.env(\..+)?$' | grep -vE '(^|/)\.env\.example$')
if [ -n "$env_files" ]; then
  echo "오류: .env 파일이 추적되고 있다:"
  echo "$env_files"
  found=1
fi

# git grep: 0 = 찾음, 1 = 없음, 그 밖 = 오류.
scan() {
  local message="$1"
  shift
  git grep "$@"
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "오류: ${message}"
    found=1
  elif [ "$rc" -ne 1 ]; then
    fail_git "git grep 실패(코드 ${rc})"
  fi
}

scan "API 키(sk-…)로 보이는 문자열이 있다." -nIE 'sk-[A-Za-z0-9]{20,}'
scan "api_key 값으로 보이는 문자열이 있다." -nIiE "api[_-]?key[[:space:]]*[:=][[:space:]]*['\"][A-Za-z0-9]{16,}"
# 개인 홈·세션 절대 경로(계정 이름이 드러난다). 허용: 시험용 가짜 경로 /Users/someone/.
scan "개인 홈 절대 경로(/Users/…, -Users-…)가 있다. ~/… 나 저장소 상대 경로로 바꿀 것." -nIE -e '/Users/|-Users-' --and --not -e '/Users/someone/'

exit "$found"
