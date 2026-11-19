from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import install_error_handlers


def test_unknown_api_path_shape(client):
    r = client.get("/api/no-such-path")
    assert r.status_code == 404
    assert r.json() == {"code": "not_found", "message": "찾을 수 없습니다.", "detail": None}


def test_method_not_allowed_shape(client):
    r = client.delete("/api/auth/users")
    assert r.status_code == 405
    assert r.json() == {
        "code": "method_not_allowed",
        "message": "허용되지 않는 요청입니다.",
        "detail": None,
    }


def test_unhandled_exception_shape_hides_text():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise RuntimeError("secret-inside")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json() == {
        "code": "internal_error",
        "message": "서버에서 문제가 생겼습니다.",
        "detail": None,
    }
    assert "secret-inside" not in r.text
