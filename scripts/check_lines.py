"""파일·함수 줄 수 검사. 상한을 넘으면 종료 코드 1, 권장만 넘으면 경고만 한다.

파일: frontend/src ts/tsx 300/600, backend/app py 400/800.
함수: backend/app py 50/100 (ast 로 잰다. 화면 함수는 eslint 가 검사).

사용: python scripts/check_lines.py <저장소 루트>
"""

import ast
import sys
from pathlib import Path

# (기준 폴더, 확장자, 권장, 상한, 제외할 하위 폴더)
RULES = [
    ("frontend/src", {".ts", ".tsx"}, 300, 600, ()),
    ("backend/app", {".py"}, 400, 800, ("domains",)),
]
FUNC_SOFT, FUNC_HARD = 50, 100


def is_excluded(rel: Path, skip_dirs: tuple[str, ...]) -> bool:
    if ".test." in rel.name or ".gen." in rel.name:
        return True
    return "tests" in rel.parts[:-1] or rel.parts[0] in skip_dirs


def report(label: str, count: int, soft: int, hard: int) -> bool:
    """상한을 넘으면 True. 권장만 넘으면 경고를 찍고 False."""
    if count > hard:
        print(f"오류: {label} {count}줄 (상한 {hard})")
        return True
    if count > soft:
        print(f"경고: {label} {count}줄 (권장 {soft})")
    return False


def function_lengths(text: str):
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name, node.lineno, node.end_lineno - node.lineno + 1


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
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(root).as_posix()
            failed |= report(rel, len(text.splitlines()), soft, hard)
            if path.suffix == ".py":
                for name, lineno, count in function_lengths(text):
                    label = f"{rel}:{lineno} {name}()"
                    failed |= report(label, count, FUNC_SOFT, FUNC_HARD)
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("사용: python scripts/check_lines.py <저장소 루트>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(Path(sys.argv[1])))
