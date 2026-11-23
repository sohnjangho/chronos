"""카카오톡 연결(계획 4 Task 101) — 문안 도우미, 「준비되지 않음」, 문의 문자 대신 보내기, 목록 읽기의 상한·지우기.

[PM 11-23] 카카오톡은 연결만 만들고 쓰지 않는다: 카카오톡 통로는 없고(등록하지 않음), 받는 길도 없다. 실제 제공사·망을 부르지
않는다(KatMock·가짜 목록). 번호·키는 모두 가상이다.
"""

import ast
from pathlib import Path

import pytest

import app
from app.outreach import kakao, provider
from app.outreach.harness import events, registry
from app.outreach.harness.types import Ref
from app.outreach.provider import (
    KakaoChannelInfo,
    KakaoTemplateInfo,
    KatClient,
    ProviderConn,
    ProviderFailed,
)
from app.store.tables_outreach import KakaoTemplate
from tests.harness_doubles import FakeChannel
from tests.outreach.harness.test_gate import (
    connect,
    message,
    person,
    reread,
    send,
    trail,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY, SENTINEL_PHONE
from tests.provider_doubles import KAT_ACCOUNT, KAT_BASE, KatMock, RunawayFake

pytestmark = pytest.mark.usefixtures("time_guard")

APP = Path(app.__file__).resolve().parent
BODY = "#{이름}님, #{날짜} 타설 예정입니다. 가능 여부를 알려 주세요.\n답은 이 번호로 문자 주세요: 070-0000-0000"


def template(session, conn, **over) -> KakaoTemplate:
    values = {"connection_id": conn.id, "channel": "ch-1", "provider_template_id": "tpl-1", "use": "체크인 요청",
              "body": BODY, "variables_json": ["이름", "날짜"], "status": "approved", **over}
    row = KakaoTemplate(**values)
    session.add(row)
    session.flush()
    return row


class Lister:
    """kakao_channels·kakao_templates 만 있는 제공사 가짜. 부름 수에 상한이 있다(넘으면 RunawayFake)."""

    LIMIT = 60

    def __init__(self, channels: list[KakaoChannelInfo], templates: dict[str, list[KakaoTemplateInfo]]) -> None:
        self.channels, self.templates, self.calls = channels, templates, []

    def _count(self, what: str) -> None:
        self.calls.append(what)
        if len(self.calls) > self.LIMIT:
            raise RunawayFake("카카오 목록 가짜를 너무 많이 불렀습니다")

    async def kakao_channels(self) -> list[KakaoChannelInfo]:
        self._count("channels")
        return list(self.channels)

    async def kakao_templates(self, channel: str) -> list[KakaoTemplateInfo]:
        self._count(channel)
        return list(self.templates.get(channel, []))


def channel(n: int, **over) -> KakaoChannelInfo:
    return KakaoChannelInfo(**{"id": f"ch-{n}", "name": f"크로노스 현장 {n}", "status": "connected", **over})


def tpl(n: int, status: str = "approved", body: str = BODY) -> KakaoTemplateInfo:
    return KakaoTemplateInfo(id=f"tpl-{n}", body=body, status=status)


# ── 문안 도우미 ─────────────────────────────────────────────────────


def test_variables_and_fill(session):
    assert kakao.variables("#{이름}님 #{날짜}에 #{이름}님께") == ["이름", "날짜"]
    assert kakao.variables("변수 없음") == []
    assert kakao.fill("#{이름}님 #{날짜}", {"이름": "박현장", "날짜": "11월 30일", "남는것": "x"}) == "박현장님 11월 30일"
    for missing in ({"이름": "박현장"}, {"이름": "박현장", "날짜": "  "}, {"이름": "박현장", "날짜": ""}):
        with pytest.raises(kakao.KakaoError):
            kakao.fill("#{이름}님 #{날짜}", missing)
    row = template(session, connect(session))
    assert kakao.fill(row, {"이름": "박현장", "날짜": "11월 30일"}).startswith("박현장님, 11월 30일 타설")


@pytest.mark.parametrize("status,use,expected", [("approved", "체크인 요청", True), ("approved", None, False),
                                                 ("approved", "", False), ("reviewing", "체크인 요청", False),
                                                 ("rejected", "체크인 요청", False), ("dormant", "체크인 요청", False)])
def test_usable_needs_approval_and_a_use(session, status, use, expected):
    assert kakao.usable(template(session, connect(session), status=status, use=use)) is expected


@pytest.mark.parametrize("body,sender,expected", [
    ("답은 이 번호로 문자 주세요", None, True),
    ("답은 070-****-0123 으로 문자 주세요", "07000000123", True),
    ("답은 0123 으로 문자 주세요", "070-0000-0123", True),
    ("답은 070-****-0123 으로 문자 주세요", None, False),
    ("답은 070-****-0123 으로 문자 주세요", "07000000999", False),
    ("답은 이 번호로 전화 주세요", "07000000123", False),  # 「문자」가 없다
    ("문자 주세요", "07000000123", False),  # 어느 번호로인지가 없다
])
def test_reply_line_flag(body, sender, expected):
    assert kakao.has_reply_line(body, sender) is expected


def test_not_ready_while_no_kakao_channel_is_registered(session):
    assert kakao.ready(session) is False  # 연결도 없음
    conn = connect(session)
    template(session, conn)  # 승인됐고 쓰는 곳이 이어진 문안
    session.commit()
    assert kakao.ready(session) is False  # 카카오톡 통로가 등록돼 있지 않다
    with registry.pinned({"kakao": FakeChannel().lane("kakao")}):  # 통로가 생긴 뒤에야(가짜로만) 참이 될 수 있다
        assert kakao.ready(session) is True
    assert kakao.ready(session) is False


async def test_kakao_row_goes_as_sms_through_gate(session, sid):
    """문 차례 7 은 그대로: 승인된 문안이 있어도 카카오톡 통로가 없으니 문자로 — 줄의 채널 sms, 사건 kakao_not_ready."""
    conn = connect(session)
    row_template = template(session, conn)
    row = message(session, person(session, sid), channel="kakao", body="", template_id=row_template.id,
                  template_vars_json={"이름": "박현장", "날짜": "11월 30일"})
    session.commit()
    fake = FakeChannel()

    with registry.pinned({"sms": fake.lane("sms")}):  # 문자만 가짜 — 카카오톡은 등록되지 않은 그대로
        out = await send(row)

    row = reread(session, row)
    assert out.code == "accepted" and [d.channel for d in fake.delivered] == ["sms"] and row.channel == "sms"
    assert row.body.startswith("박현장님, 11월 30일 타설 예정입니다.")
    assert trail(session, row) == [("kakao_not_ready", "noted"), ("channel_choice", "allowed"), ("delivery", "allowed")]
    assert events.of(session, Ref("message", row.id))[1]["detail"] == "sms"


# ── 받는 길·카카오톡 통로가 없음 ────────────────────────────────────


def _calls(name: str):
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) == name:
                yield path, node


def test_no_inbound_path_for_kakao():
    """받은 줄(direction "in")을 만드는 곳은 모두 channel "sms" 다. 제공사 호출에 카카오톡을 받는 길이 없다."""
    found = []
    for path, node in _calls("OutreachMessage"):
        words = {k.arg: k.value.value for k in node.keywords if isinstance(k.value, ast.Constant)}
        if words.get("direction") == "in":
            found.append((path.name, words.get("channel")))
    assert found and all(channel == "sms" for _, channel in found), found
    kakao_methods = {name for name in vars(KatClient) if "kakao" in name}
    assert kakao_methods == {"kakao_channels", "kakao_templates"}  # 목록 읽기뿐 — 받기·보내기 따로 없음


def test_no_kakao_deliver_exists():
    """카카오톡 통로(나중 작업)는 없다: 통로 파일도, kakao 이름의 register_channel 도 없다."""
    assert not (APP / "outreach" / "channels" / "kakao.py").exists()
    registering = [(p.name, n.lineno) for p, n in _calls("register_channel")
                   if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "kakao"]
    assert registering == []
    import app.main  # noqa: F401 — 앱이 불러오는 모듈이 모두 올라온 뒤에도
    assert "kakao" not in registry._CHANNELS


# ── 제공사: 목록 읽기는 확인되지 않음 ──────────────────────────────


async def test_listing_is_not_confirmed_and_sends_nothing():
    mock = KatMock()
    client = KatClient(ProviderConn(base_url=KAT_BASE, account_id=KAT_ACCOUNT, key=SENTINEL_KEY), transport=mock)
    assert provider.KAKAO_LISTING_CONFIRMED is False
    for call in (client.kakao_channels(), client.kakao_templates("ch-1")):
        with pytest.raises(ProviderFailed) as caught:
            await call
        assert caught.value.code == "not_confirmed" and caught.value.message == provider.KAKAO_NOT_CONFIRMED
        assert caught.value.maybe_sent is False
    assert mock.requests == []


# ── 목록 읽기: 상한 ─────────────────────────────────────────────────


async def test_read_listing_caps_requests_and_items():
    many = Lister([channel(n) for n in range(kakao.MAX_CHANNELS + 5)],
                  {f"ch-{n}": [tpl(n * 100 + i) for i in range(80)] for n in range(kakao.MAX_CHANNELS + 5)})
    got = await kakao.read_listing(many)
    assert len(many.calls) <= 1 + kakao.MAX_CHANNELS  # 채널 목록 한 번 + 채널마다 한 번
    assert len(got.channels) == kakao.MAX_CHANNELS and len(got.templates) == kakao.MAX_TEMPLATES
    assert got.truncated is True

    few = Lister([channel(1)], {"ch-1": [tpl(1), tpl(2, "reviewing")]})
    got = await kakao.read_listing(few)
    assert few.calls == ["channels", "ch-1"] and len(got.templates) == 2 and got.truncated is False


async def test_read_listing_with_no_channel_asks_once():
    empty = Lister([], {})
    got = await kakao.read_listing(empty)
    assert (got.channels, got.templates, got.truncated, empty.calls) == ([], [], False, ["channels"])


# ── 지우기: 번호는 끝 4자리만, 키·Account ID·보이지 않는 글자는 없음 ──


def test_clean_masks_numbers_but_keeps_last_four():
    body = (f"#{{이름}}님 {SENTINEL_PHONE} 으로 확인했습니다. 키 {SENTINEL_KEY} 계정 {KAT_ACCOUNT}\u202e\x07\n"
            "답은 070-0000-0123 으로 문자 주세요")
    got = kakao.clean(kakao.Listing([channel(1, name=f"현장 {SENTINEL_PHONE}")],
                                    [("ch-1", tpl(1, body=body))], False), [SENTINEL_KEY, KAT_ACCOUNT])
    text = got.templates[0][1].body
    assert "010-****-0199" in text and "070-****-0123" in text and "\n답은" in text
    assert SENTINEL_DIGITS not in "".join(c for c in text if c.isdigit())
    assert SENTINEL_KEY not in text and KAT_ACCOUNT not in text and "\u202e" not in text and "\x07" not in text
    assert kakao.has_reply_line(text, "07000000123")
    assert SENTINEL_DIGITS not in "".join(c for c in got.channels[0].name if c.isdigit())


def test_clean_drops_unusable_ids_and_unknown_words():
    rows = kakao.Listing(
        [channel(1), channel(2, id=SENTINEL_DIGITS), channel(3, id="ch 3"), channel(4, status="Connected!")],
        [("ch-1", tpl(1, status="weird")), ("ch-1", KakaoTemplateInfo(id=SENTINEL_DIGITS, body=BODY, status="approved")),
         ("ch-1", KakaoTemplateInfo(id=SENTINEL_KEY, body=BODY, status="approved")), ("ch-1", tpl(1))],
        False)
    got = kakao.clean(rows, [SENTINEL_KEY])
    assert [c.id for c in got.channels] == ["ch-1", "ch-4"] and got.channels[1].status == "unknown"
    assert [(ch, t.id, t.status) for ch, t in got.templates] == [("ch-1", "tpl-1", "reviewing")]  # 겹친 id 는 첫 줄만


def test_clean_cuts_long_text():
    long = kakao.clean(kakao.Listing([channel(1, name="가" * 500)], [("ch-1", tpl(1, body="나" * 5000))], False), [])
    assert len(long.channels[0].name) == kakao.NAME_MAX and len(long.templates[0][1].body) == kakao.BODY_MAX
