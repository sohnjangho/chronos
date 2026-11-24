"""개발 콘솔 업데이트 내역: deploy/updates.jsonl 을 새것부터, 관리자만, 서버가 켤 때 읽은 자기 커밋(running_commit)."""

import json
import subprocess

import pytest

from app.programs.devconsole import updates
from app.programs.devconsole.schemas import (
    HealthOut,
    KakaoHealthOut,
    NotifyHealthOut,
    VoiceHealthOut,
)
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from tests.helpers import auth

URL = "/api/devconsole/updates"


def entry(at: str, commit: str, title: str, **kw) -> str:
    return json.dumps({"at": at, "commit": commit, "title": title, **kw}, ensure_ascii=False)


@pytest.fixture
def log_file(tmp_path, monkeypatch):
    path = tmp_path / "updates.jsonl"
    monkeypatch.setattr(updates, "UPDATES_FILE", path)
    monkeypatch.setattr(updates, "RUNNING_COMMIT", None)
    return path


@pytest.fixture
def field(session) -> dict[str, str]:
    row = User(login_id="site1", name="박현장", role="field", password_hash=hash_password("field-pass"))
    session.add(row)
    session.commit()
    return auth(issue_token(row.id))


def test_admin_only(client, user, field, log_file):
    assert client.get(URL).status_code == 401
    for headers in (user, field):
        r = client.get(URL, headers=headers)
        assert (r.status_code, r.json()["code"]) == (403, "admin_only")


def test_entries_newest_first_with_items_and_notice(client, admin, log_file):
    log_file.write_text(
        "\n".join([
            entry("2026-11-24T08:47+09:00", "79cd19d", "음성 연결 고침",
                  fixed=[{"text": "AI 전화의 음성 연결이 다시 됩니다", "note": "Gemini Live v1alpha 로 연결"}]),
            entry("2026-11-24T14:12+09:00", "c5f1c23", "기기 이어 쓰기", notice="모두 한 번 다시 로그인",
                  added=["새 아이콘 20종"], safety=["잃어버린 기기는 그 기기만 골라 로그아웃"]),
            entry("2026-11-24T12:01+09:00", "5c69aab", "받는 전화"),
        ]) + "\n",
        encoding="utf-8",
    )
    body = client.get(URL, headers=admin).json()
    assert [e["commit"] for e in body["entries"]] == ["c5f1c23", "5c69aab", "79cd19d"]
    top = body["entries"][0]
    assert top["notice"] == "모두 한 번 다시 로그인"
    assert top["added"] == [{"text": "새 아이콘 20종", "note": None}]
    assert top["fixed"] == []
    assert top["at"].startswith("2026-11-24T14:12:00+09:00")
    assert body["entries"][2]["fixed"] == [{"text": "AI 전화의 음성 연결이 다시 됩니다", "note": "Gemini Live v1alpha 로 연결"}]
    assert body["entries"][1]["notice"] is None
    assert body["running_commit"] is None


def test_malformed_lines_are_skipped(client, admin, log_file):
    log_file.write_text(
        "\n".join([
            "{not json",
            "[1, 2]",
            "",
            entry("어제", "abc1234", "때가 글"),
            entry("2026-11-24T10:00", "abc1234", "시간대 없음"),
            entry("2026-11-24T10:00+09:00", "", "커밋 없음"),
            entry("2026-11-24T10:00+09:00", "abc1234", ""),
            entry("2026-11-24T10:00+09:00", "zz; rm", "커밋이 이상함"),
            entry("2026-11-24T10:00+09:00", "abc1234", "칸이 목록 아님", added="하나"),
            entry("2026-11-24T10:00+09:00", "abc1234", "항목이 이상함", fixed=[3]),
            entry("2026-11-24T11:00+09:00", "def5678", "멀쩡함", added=["좋음"]),
        ]),
        encoding="utf-8",
    )
    body = client.get(URL, headers=admin).json()
    assert [e["title"] for e in body["entries"]] == ["멀쩡함"]


def test_missing_file_is_an_empty_list(client, admin, log_file):
    body = client.get(URL, headers=admin).json()
    assert body == {"entries": [], "running_commit": None}


def test_at_most_200_newest(client, admin, log_file):
    lines = [entry(f"2026-11-{1 + i // 24:02d}T{i % 24:02d}:00+09:00", f"{i:07x}", f"판 {i}") for i in range(230)]
    log_file.write_text("\n".join(lines), encoding="utf-8")
    got = client.get(URL, headers=admin).json()["entries"]
    assert len(got) == updates.MAX_ENTRIES == 200
    assert got[0]["title"] == "판 229" and got[-1]["title"] == "판 30"


def test_file_size_cap_reads_only_the_tail(client, admin, log_file, monkeypatch):
    monkeypatch.setattr(updates, "MAX_BYTES", 400)
    old = entry("2026-11-20T09:00+09:00", "1111111", "오래된 판", added=["가" * 300])
    new = entry("2026-11-24T09:00+09:00", "2222222", "새 판")
    log_file.write_text(old + "\n" + new + "\n", encoding="utf-8")
    assert log_file.stat().st_size > 400
    assert [e["title"] for e in client.get(URL, headers=admin).json()["entries"]] == ["새 판"]


def test_running_commit_marks_the_live_entry(client, admin, log_file, monkeypatch):
    monkeypatch.setattr(updates, "RUNNING_COMMIT", "c5f1c23")
    log_file.write_text(entry("2026-11-24T14:12+09:00", "c5f1c23", "기기 이어 쓰기") + "\n", encoding="utf-8")
    body = client.get(URL, headers=admin).json()
    assert body["running_commit"] == "c5f1c23"
    assert body["entries"][0]["commit"] == body["running_commit"]


# ── 서버가 켤 때 읽는 자기 커밋(git rev-parse --short HEAD, 2초, 셸 없음) ──


def test_read_running_commit_uses_git_without_shell(monkeypatch):
    seen = {}

    def fake_run(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return subprocess.CompletedProcess(args, 0, stdout="c5f1c23\n", stderr="")

    monkeypatch.setattr(updates.subprocess, "run", fake_run)
    assert updates.read_running_commit() == "c5f1c23"
    assert seen["args"] == ["git", "rev-parse", "--short", "HEAD"]
    assert seen["kw"]["timeout"] == 2
    assert seen["kw"].get("shell", False) is False
    assert seen["kw"]["cwd"] == updates.REPO_ROOT


@pytest.mark.parametrize(
    "outcome",
    [
        subprocess.TimeoutExpired(["git"], 2),
        FileNotFoundError("git"),
        subprocess.CompletedProcess(["git"], 128, stdout="", stderr="fatal: not a git repository"),
        subprocess.CompletedProcess(["git"], 0, stdout="not a sha\n", stderr=""),
    ],
)
def test_read_running_commit_failure_is_none(monkeypatch, outcome):
    def fake_run(args, **kw):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(updates.subprocess, "run", fake_run)
    assert updates.read_running_commit() is None


def test_repo_root_holds_the_deploy_log():
    assert updates.UPDATES_FILE == updates.REPO_ROOT / "deploy" / "updates.jsonl"
    assert (updates.REPO_ROOT / "backend" / "app").is_dir()


# ── 진단 칸 계약: 서버 응답 모델의 칸 이름 = 화면 대응표가 읽는 고정본(frontend …/__fixtures__/health-fields.json) ──


def test_health_fields_fixture_matches_the_response_model():
    """서버가 진단 칸을 더하거나 빼면 여기서 깨진다 → 고정본을 고치면 화면 시험(healthChecks.test)이 대응표에 더하라고 깨진다."""
    fixture = updates.REPO_ROOT / "frontend" / "src" / "programs" / "devconsole" / "__fixtures__" / "health-fields.json"
    want = {
        "top": sorted(HealthOut.model_fields),
        "notify": sorted(NotifyHealthOut.model_fields),
        "kakao": sorted(KakaoHealthOut.model_fields),
        "voice": sorted(VoiceHealthOut.model_fields),
    }
    got = json.loads(fixture.read_text(encoding="utf-8"))
    assert got == want, f"{fixture} 를 이 값으로 고치고 화면 대응표에 새 칸을 더하세요:\n{json.dumps(want, ensure_ascii=False, indent=2)}"
