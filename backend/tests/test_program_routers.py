"""프로그램 라우터 자동 등록(app.main.include_program_routers): 같은 라우터는 한 번만, 라우터 없는 router.py 는 오류."""

import importlib
from collections import Counter

import pytest
from fastapi import APIRouter

import app.main as main_module
from app.main import include_program_routers


class Recorder:
    """FastAPI 대신 include_router 로 받은 라우터를 적어 둔다."""

    def __init__(self) -> None:
        self.routers: list[APIRouter] = []

    def include_router(self, router: APIRouter) -> None:
        self.routers.append(router)


def _endpoints(routers: list[APIRouter]) -> list[tuple[str, str]]:
    return [(m, r.path) for router in routers for r in router.routes for m in getattr(r, "methods", ())]


def _package(tmp_path, monkeypatch, files: dict[str, str]) -> str:
    """tmp_path 에 가짜 programs 묶음을 만들고 app.main 이 그것을 보게 한다. 글 안의 {pkg} 는 묶음 이름."""
    name = f"fake_{tmp_path.name}"
    for rel, text in {"__init__.py": "", **files}.items():
        path = tmp_path / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.replace("{pkg}", name))
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(main_module, "programs", importlib.import_module(name))
    return name


def test_app_routes_have_no_duplicates():
    rec = Recorder()
    include_program_routers(rec)
    endpoints = _endpoints(rec.routers)
    assert len({id(r) for r in rec.routers}) == len(rec.routers)
    assert [k for k, n in Counter(endpoints).items() if n > 1] == []
    assert ("GET", "/api/schedules/{schedule_id}/progress") in endpoints


def test_shared_router_is_included_once(tmp_path, monkeypatch):
    _package(tmp_path, monkeypatch, {
        "a/__init__.py": "",
        "a/router.py": "from fastapi import APIRouter\nrouter = APIRouter(prefix='/a')\n\n"
                       "@router.get('/x')\ndef x() -> int:\n    return 1\n",
        "b/__init__.py": "",
        "b/router.py": "from fastapi import APIRouter\nfrom {pkg}.a.router import router as a_router\n"
                       "router = APIRouter(prefix='/b')\n",
    })
    rec = Recorder()
    assert include_program_routers(rec) == ["a", "b"]
    assert len(rec.routers) == 2  # b 가 a 의 라우터를 다시 내보내도 한 번만


def test_router_module_without_a_router_fails_loudly(tmp_path, monkeypatch):
    _package(tmp_path, monkeypatch, {"c/__init__.py": "", "c/router.py": "VALUE = 1\n"})
    with pytest.raises(RuntimeError, match="c 프로그램의 router.py 에 라우터가 없습니다"):
        include_program_routers(Recorder())
