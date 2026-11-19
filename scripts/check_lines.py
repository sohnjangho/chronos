"""파일 줄 수 검사. 상한을 넘으면 종료 코드 1, 권장만 넘으면 경고만 한다.

사용: python scripts/check_lines.py <저장소 루트>
"""

import sys
from pathlib import Path

# (기준 폴더, 확장자, 권장, 상한, 제외할 하위 폴더)
RULES = [
    ("frontend/src", {".ts", ".tsx"}, 300, 600, ()),
    ("backend/app", {".py"}, 400, 800, ("domains",)),
]


def is_excluded(rel: Path, skip_dirs: tuple[str, ...]) -> bool:
    if ".test." in rel.name or ".gen." in rel.name:
        return True
    return "tests" in rel.parts[:-1] or rel.parts[0] in skip_dirs


def main(root: Path) -> int:
    failed = False
    for folder, exts, soft, hard, skip_dirs in RULES:
        base = root / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in exts or not path.is_file():
                continue
            if is_excluded(path.relative_to(base), skip_dirs):
                continue
            count = len(path.read_text(encoding="utf-8").splitlines())
            rel = path.relative_to(root).as_posix()
            if count > hard:
                print(f"오류: {rel} {count}줄 (상한 {hard})")
                failed = True
            elif count > soft:
                print(f"경고: {rel} {count}줄 (권장 {soft})")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용: python scripts/check_lines.py <저장소 루트>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
