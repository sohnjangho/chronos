"""카카오톡(알림톡) 연결 — 채널·문안 상태 읽기만(계획 4 Task 101). [PM 11-23] 연결만 만들고 쓰지 않는다.

- **카카오톡 통로는 등록하지 않는다**(app/outreach/channels/ 에 kakao 가 없다). 그래서 `ready` 는 지금 늘 거짓이고, 나가는 문은
  카카오톡 줄을 문자로 보낸다(Task 65 차례 7 — 사건 kakao_not_ready). 나중에 통로를 만들 때도 한 번만 등록하고, 시험은
  `registry.pinned(...)` 로만 가짜를 끼운다.
- **카카오톡으로 들어오는 것은 없다**(알림톡은 보내기만). 답은 문안 끝의 「이 번호로 문자」 줄로 문자로 받는다(`has_reply_line`).
- 목록 읽기(`read_listing`): 채널 목록 1번 + 채널마다 1번, 채널은 `MAX_CHANNELS` 개까지 — 한 번에 요청은 많아야
  1 + MAX_CHANNELS 번. 문안은 모두 합쳐 `MAX_TEMPLATES` 개까지. 상한을 넘으면 뒤는 읽지 않고 `truncated` 를 세운다 — 그때는
  「없어진 문안」을 가를 수 없으므로 `save` 가 아무 줄도 dormant 로 바꾸지 않는다(다음 맞추기도 같은 앞부분만 읽는다 — 화면이
  알릴 일이다). 제공사 호출 안의 쪽 나눔 상한은 provider 쪽 몫이다(목록 읽는 길이 확인되면 거기 둔다).
- 제공사 글은 `clean` 을 거친 뒤에만 저장·표시한다: NFC · 줄 나눔은 \\n · 보이지 않는 글자(제어·글 방향·폭 없는 글자·꼬리표·
  짝 없는 서로게이트) 빼기 · 키·Account ID 지우기 · 번호는 끝 4자리만 남긴 가린 꼴(`070-****-0123` — `has_reply_line` 이 끝 4자리를
  본다. 그 꼴로 맞출 수 없는 번호는 `[번호]`) · 길이 상한(이름 `NAME_MAX`, 본문 `BODY_MAX`). 꼴이 틀린 id 와 전화번호·키로 보이는
  id 의 줄은 버린다.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.info import generic
from app.outreach import phone, redact
from app.outreach.harness import registry
from app.outreach.harness.types import NotReady
from app.outreach.provider import KakaoChannelInfo, KakaoTemplateInfo
from app.store import outreach
from app.store.tables_outreach import KakaoTemplate, NotifyConnection

MAX_CHANNELS = 10  # 한 번 맞출 때 읽는 채널 수(채널마다 요청 하나)
MAX_TEMPLATES = 300  # 한 번 맞출 때 받는 문안 수(모든 채널 합)
NAME_MAX = 100  # 채널 이름(글자)
BODY_MAX = 1000  # 문안 본문(글자) — 문자 본문 상한과 같다
STATUSES = ("approved", "reviewing", "rejected")  # 제공사에서 오는 상태. 사라진 문안은 우리가 dormant 로
NOT_READY = ("카카오톡(알림톡)은 아직 쓸 수 없습니다 — 사업자 인증 채널과 승인된 문안이 준비된 뒤에 열립니다. "
             "지금은 문자로 보내 주세요.")
_SLOT = re.compile(r"#\{([^}]*)\}")  # 문안의 빈 칸 — 나가는 문(gate._SLOT)과 같은 꼴
_ID = re.compile(r"(?=.*[A-Za-z0-9])[A-Za-z0-9_.:\-]{1,100}")
_WORD = re.compile(r"[a-z][a-z_\-]{0,19}")
_NOT_DIGIT = re.compile(r"\D")
_LINE_BREAK = re.compile(r"\r\n?|[  ]")
_HIDDEN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\ud800-\udfff"
                     r"\U000e0000-\U000e007f]")


class KakaoError(ValueError):
    """문안을 채울 수 없다(빈 변수). 글에 변수 이름만 있다."""


# ── 문안 도우미 ─────────────────────────────────────────────────────


def variables(body: str) -> list[str]:
    """문안의 `#{이름}` 변수 이름(처음 나온 차례, 겹치지 않게)."""
    return list(dict.fromkeys(_SLOT.findall(body or "")))


def fill(template: KakaoTemplate | str, values: dict) -> str:
    """변수를 채운 글. 채우지 않았거나 빈 값인 변수가 하나라도 있으면 KakaoError(반쯤 채운 글은 만들지 않는다)."""
    body = template if isinstance(template, str) else template.body
    empty = [name for name in variables(body) if not isinstance(values.get(name), str) or not values[name].strip()]
    if empty:
        raise KakaoError(f"채우지 않은 변수가 있습니다: {', '.join(empty)}")
    return _SLOT.sub(lambda slot: values[slot.group(1)], body)


def usable(template: KakaoTemplate) -> bool:
    """승인됐고 쓰는 곳(use)이 이어진 문안."""
    return template.status == "approved" and bool(template.use)


def has_reply_line(body: str, sender_number: str | None) -> bool:
    """답을 문자로 받는 줄이 있는가: 「문자」와 「이 번호」 또는 우리 발신번호 끝 4자리."""
    if "문자" not in (body or ""):
        return False
    if "이 번호" in body:
        return True
    digits = _NOT_DIGIT.sub("", sender_number or "")
    return len(digits) >= 4 and digits[-4:] in body


def ready(session: Session) -> bool:
    """카카오톡으로 보낼 수 있는가 — 카카오톡 통로가 등록돼 있고 기본 연결에 쓸 수 있는 문안이 있어야 참. 지금은 통로가 없어 늘 거짓."""
    try:
        registry.channel("kakao")
    except NotReady:
        return False
    conn = outreach.connection(session)
    if conn is None:
        return False
    rows = session.scalars(select(KakaoTemplate).where(KakaoTemplate.connection_id == conn.id,
                                                       KakaoTemplate.status == "approved"))
    return any(usable(row) for row in rows)


# ── 목록 읽기·지우기·맞추기 ─────────────────────────────────────────


class Lister(Protocol):
    async def kakao_channels(self) -> list[KakaoChannelInfo]: ...

    async def kakao_templates(self, channel: str) -> list[KakaoTemplateInfo]: ...


@dataclass(frozen=True)
class Listing:
    """한 번 읽은 것. templates 는 (채널 id, 문안). truncated 면 상한 뒤에 읽지 않은 것이 있을 수 있다."""

    channels: list[KakaoChannelInfo]
    templates: list[tuple[str, KakaoTemplateInfo]]
    truncated: bool


async def read_listing(client: Lister) -> Listing:
    """채널 목록 한 번, 채널마다 문안 한 번(모듈 머리 글의 상한). 실패는 부른 쪽으로(ProviderFailed) — 반쯤 읽은 것은 버린다."""
    found = await client.kakao_channels()
    truncated = len(found) > MAX_CHANNELS
    channels = list(found[:MAX_CHANNELS])
    templates: list[tuple[str, KakaoTemplateInfo]] = []
    for each in channels:
        room = MAX_TEMPLATES - len(templates)
        if room <= 0:  # 남은 채널은 묻지 않는다
            truncated = True
            break
        got = await client.kakao_templates(each.id)
        truncated = truncated or len(got) > room
        templates += [(each.id, item) for item in got[:room]]
    return Listing(channels, templates, truncated)


def _mask_numbers(text: str) -> str:
    """번호를 끝 4자리만 남긴 가린 꼴로. 자리를 맞출 수 없으면 redact.hide_phones 그대로(모두 `[번호]` — 더 가린 쪽)."""
    hidden = redact.hide_phones(text)
    mark = redact.PHONE_MASK
    if hidden == text or mark in text:
        return hidden
    pieces = hidden.split(mark)  # 번호 밖의 글은 hide_phones 가 그대로 둔다 — 그 조각 사이가 번호 자리다
    if not text.startswith(pieces[0]):
        return hidden
    spans, pos = [], len(pieces[0])
    for index, after in enumerate(pieces[1:], 1):
        last = index == len(pieces) - 1
        end = len(text) - len(after) if last else (text.find(after, pos + 1) if after else -1)
        if end <= pos or (last and not text.endswith(after)):
            return hidden
        spans.append((pos, end))
        pos = end + len(after)
    if any(redact.hide_phones(text[a:b]) != mark for a, b in spans):  # 맞춘 자리마다 그 자체가 번호여야
        return hidden
    out = [pieces[0]]
    for (a, b), after in zip(spans, pieces[1:], strict=True):
        number = phone.normalize(text[a:b])
        shown = phone.mask(number) if number else ""
        out += [shown if shown.count("-") == 2 else mark, after]
    return "".join(out)


def _text(raw: object, secrets: list[str], limit: int, *, lines: bool) -> str:
    text = unicodedata.normalize("NFC", raw) if isinstance(raw, str) else ""
    text = _HIDDEN.sub("", _LINE_BREAK.sub("\n", text))
    if not lines:
        text = re.sub(r"\s+", " ", text).strip()
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= redact.MIN_SECRET:
            text = generic.scrub(text, secret)
    return _mask_numbers(text)[:limit]


def _safe_id(value: object, secrets: list[str]) -> str | None:
    """제공사 id: 꼴이 맞고 전화번호·키·Account ID 가 아닐 때만."""
    if not isinstance(value, str) or not _ID.fullmatch(value) or phone.normalize(value) is not None:
        return None
    if any(generic.key_survives(value, s) for s in secrets if isinstance(s, str) and len(s) >= redact.MIN_SECRET):
        return None
    return value


def clean(listing: Listing, secrets: list[str]) -> Listing:
    """저장·표시할 꼴로(모듈 머리 글). 버린 채널의 문안·같은 id 의 둘째 줄도 버린다."""
    channels: dict[str, KakaoChannelInfo] = {}
    for each in listing.channels:
        key = _safe_id(each.id, secrets)
        if key is not None and key not in channels:
            status = each.status if isinstance(each.status, str) and _WORD.fullmatch(each.status) else "unknown"
            channels[key] = KakaoChannelInfo(id=key, name=_text(each.name, secrets, NAME_MAX, lines=False), status=status)
    templates: dict[tuple[str, str], KakaoTemplateInfo] = {}
    for channel_id, item in listing.templates:
        key = _safe_id(item.id, secrets)
        if channel_id not in channels or key is None or (channel_id, key) in templates:
            continue
        status = item.status if item.status in STATUSES else "reviewing"  # 모르는 상태 말은 승인 아닌 쪽으로
        templates[(channel_id, key)] = KakaoTemplateInfo(id=key, body=_text(item.body, secrets, BODY_MAX, lines=True),
                                                         status=status)
    return Listing(list(channels.values()), [(ch, t) for (ch, _), t in templates.items()], listing.truncated)


def save(session: Session, conn: NotifyConnection, listing: Listing, now: datetime) -> None:
    """지운 목록(clean 뒤)으로 맞춘다 — 부른 쪽이 쓰기 트랜잭션을 열고 commit 한다. 우리가 이은 use·fallback_body 는 건드리지
    않는다. 다 읽었을 때(truncated 가 아닐 때)만 목록에 없는 문안을 dormant 로."""
    rows = session.scalars(select(KakaoTemplate).where(KakaoTemplate.connection_id == conn.id))
    known = {(row.channel, row.provider_template_id): row for row in rows}
    seen = set()
    for channel_id, item in listing.templates:
        row = known.get((channel_id, item.id))
        if row is None:
            row = KakaoTemplate(connection_id=conn.id, channel=channel_id, provider_template_id=item.id)
            session.add(row)
            known[(channel_id, item.id)] = row
        row.body, row.variables_json, row.status = item.body, variables(item.body), item.status
        row.reply_line, row.synced_at = has_reply_line(item.body, conn.sender_number), now
        seen.add((channel_id, item.id))
    if not listing.truncated:
        for key, row in known.items():
            if key not in seen:
                row.status, row.synced_at = "dormant", now
    conn.kakao_channels_json = [{"id": c.id, "name": c.name, "status": c.status} for c in listing.channels]
