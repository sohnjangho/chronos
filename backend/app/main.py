import importlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI

from app import programs
from app.config import Settings, validate_settings
from app.db import close_db, get_session, init_db
from app.errors import install_error_handlers
from app.files import jobs
from app.programs.files.guard import UploadGuard
from app.store.workflows import close_unfinished
from app.tools import registry


def include_program_routers(target: FastAPI) -> list[str]:
    """app/programs/*/router.py 를 프로그램 이름 순으로 불러, 이름이 router 로 끝나는 APIRouter 를 모두 붙인다.

    새 프로그램은 router.py 만 두면 등록된다(이 파일을 고치지 않는다). 돌려주는 것은 라우터를 붙인 프로그램 이름.
    같은 라우터 객체(다른 router.py 가 다시 내보낸 것)는 한 번만 붙인다. 라우터가 없는 router.py 는 시작할 때 오류다.
    """
    names, seen = [], set()
    for path in sorted(Path(programs.__file__).parent.glob("*/router.py"), key=lambda p: p.parent.name):
        name = path.parent.name
        module = importlib.import_module(f"{programs.__name__}.{name}.router")
        routers = [v for k, v in vars(module).items() if k.endswith("router") and isinstance(v, APIRouter)]
        if not routers:
            raise RuntimeError(f"{name} 프로그램의 router.py 에 라우터가 없습니다(이름이 router 로 끝나는 APIRouter).")
        for router in routers:
            if id(router) not in seen:
                seen.add(id(router))
                target.include_router(router)
        names.append(name)
    return names


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_settings(Settings())
    init_db()
    with contextmanager(get_session)() as session:
        close_unfinished(session)  # 지난번에 끝나지 못한 실행 기록은 stopped 로 닫는다
    registry.load_all()  # 에이전트가 쓸 도구를 모두 등록한다
    jobs.start()  # 파일 뒤 작업 줄(임베딩·분류·다시 넣기). CHRONOS_QDRANT_URL 이 빈 값이면 뜻 검색만 끈다(분류는 된다)
    yield
    await jobs.stop()
    close_db()


app = FastAPI(title="ChronOS", lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(UploadGuard)  # 파일 받기: 몸을 읽기 전에 로그인·크기를 본다
include_program_routers(app)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
