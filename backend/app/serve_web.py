"""빌드한 화면(app/web, scripts/build-web.sh 가 만든다)을 서버가 직접 내준다 — chronos 명령(app.cli)만 쓴다.

개발·Docker·실서버는 vite 가 화면을 내므로 이것을 부르지 않는다(app.main 은 그대로).
/api 는 손대지 않고, 모르는 길(깊은 링크)은 index.html 로 돌려 화면이 길을 읽게 한다.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

WEB_DIR = Path(__file__).parent / "web"
_FILE_ONLY = ("api", "assets", "media")  # 이 아래에서 없는 파일은 index.html 이 아니라 404


def install_web(app: FastAPI, web_dir: Path = WEB_DIR) -> bool:
    """web_dir 에 index.html 이 있으면 모든 라우터 뒤에 화면 길을 붙이고 True. 없으면 아무것도 하지 않고 False."""
    root = web_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        target = (root / path).resolve()
        if path and target.is_file() and target.is_relative_to(root):
            return FileResponse(target)
        if path.split("/", 1)[0] in _FILE_ONLY:
            raise HTTPException(status_code=404)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True
