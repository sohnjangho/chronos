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
from app.outreach import redact, worker
from app.outreach.voice import runner
from app.points import card as points_card
from app.programs.devconsole.activity_guard import ActivityGuard
from app.programs.files.guard import UploadGuard
from app.store import settings as settings_store
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
    redact.activate()  # 로그 거르개(번호·키 지우기) — 불러오는 순서와 상관없이 건다
    init_db()
    registry.load_all()  # 에이전트가 쓸 도구를 모두 등록한다
    with contextmanager(get_session)() as session:
        close_unfinished(session)  # 지난번에 끝나지 못한 실행 기록은 stopped 로 닫는다
        for disabled in settings_store.get_disabled_tools(session):
            try:
                registry.set_enabled(disabled, False)
            except KeyError:
                pass
    jobs.start()  # 파일 뒤 작업 줄(임베딩·분류·다시 넣기). CHRONOS_QDRANT_URL 이 빈 값이면 뜻 검색만 끈다(분류는 된다)
    worker.start()  # 연락 일꾼(예약 문자·상태 조회·들어온 문자). 알림 연결이 없거나 ok 가 아니면 아무것도 하지 않는다
    runner.start()  # 거는 통화 일꾼. 끄는 설정은 문자 일꾼과 같다. 음성 백엔드가 없으면 줄의 통화를 초안으로 돌린다
    points_card.SERVING = True  # 관리 포인트 외부 영향 찾기는 서버 안에서만 뒤에서 띄운다(씨앗·명령줄은 not_started)
    yield
    points_card.SERVING = False
    await runner.stop()
    await worker.stop()
    await jobs.stop()
    close_db()


app = FastAPI(title="ChronOS", lifespan=lifespan)
install_error_handlers(app)
app.add_middleware(UploadGuard)  # 파일 받기: 몸을 읽기 전에 로그인·크기를 본다
app.add_middleware(ActivityGuard)  # 접속 기록: 응답 뒤 로그인한 사람의 요청을 한 줄 적는다
include_program_routers(app)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
