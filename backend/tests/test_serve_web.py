"""chronos 명령이 쓰는 화면 싣기(app.serve_web): 빌드한 화면을 / 에, 모르는 길은 index.html, /api 는 그대로."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.serve_web import WEB_DIR, install_web


def _web(tmp_path):
    (tmp_path / "assets").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<html>chronos</html>", encoding="utf-8")
    (tmp_path / "assets" / "main.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def _app(web_dir) -> TestClient:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert install_web(app, web_dir) is True
    return TestClient(app)


def test_serves_index_and_assets(tmp_path):
    client = _app(_web(tmp_path))
    assert client.get("/").text == "<html>chronos</html>"
    assert client.get("/assets/main.js").text == "console.log(1)"


def test_deep_link_falls_back_to_index(tmp_path):
    client = _app(_web(tmp_path))
    res = client.get("/schedules/3/gantt")
    assert res.status_code == 200
    assert res.text == "<html>chronos</html>"


def test_api_paths_unchanged(tmp_path):
    client = _app(_web(tmp_path))
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/nothing-here").status_code == 404


def test_missing_asset_is_404_not_index(tmp_path):
    client = _app(_web(tmp_path))
    assert client.get("/assets/gone.js").status_code == 404


def test_no_escape_from_web_dir(tmp_path):
    web = _web(tmp_path / "web")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    client = _app(web)
    assert "secret" not in client.get("/../secret.txt").text
    assert "secret" not in client.get("/%2e%2e/secret.txt").text


def test_without_build_nothing_is_mounted(tmp_path):
    app = FastAPI()
    assert install_web(app, tmp_path) is False
    assert TestClient(app).get("/").status_code == 404


def test_bundled_build_is_in_package():
    assert (WEB_DIR / "index.html").is_file()
    assert any((WEB_DIR / "assets").glob("*.js"))
    assert not list(WEB_DIR.rglob("*.map"))
