"""번호와 키 지우기: 모델 프롬프트·도구 결과·trace·로그·오류 글로 나가기 전에 거치는 한 곳.

hide_phones — 번호처럼 보이는 것을 `[번호]` 로.
- 숫자 묶음(반각·전각)과 한글로 읽은 숫자 묶음(공·영·일·이·삼·사·오·육·륙·칠·팔·구 — 낱말 가운데서 시작하지 않는 것,
  「에」 뒤는 된다)을 낱말 조각(token)으로 읽고, 사이가 빈칸·줄 바꿈·줄표·점·괄호·「쉼표+빈칸」·「에」(번호를 소리 내어 읽을
  때 줄표 자리: 공일공에 공공공공에 …)뿐이면 한 줄기로 잇는다. 쉼표 바로 뒤에 숫자가 오면(1,020,000) 천 단위 쉼표로 보고
  잇지 않는다. 사이에 빈칸 아닌 글자는 3개까지.
- 줄기 안에서 앞에서부터 「이어 붙인 숫자가 국내 번호 모양(phone._PARTS, `+82`·`82`·`0082` 앞머리 포함)이고, 조각의 경계가
  번호의 자리 경계(앞자리|가운데|끝 4자리, 나라 앞머리, `(0)`)에만 있는」 가장 긴 조각 묶음을 지운다. 경계를 보기 때문에
  날짜 목록(2026-02-01, 2026-02-02)이 번호로 잘못 이어지지 않는다. 줄 바꿈이 있는 경계는 보지 않고(줄이 바뀌며 묶음 가운데가
  나뉜 꼴), 한 자씩 띄운 꼴(0 1 0 …)은 경계를 보지 않는다. 바로 앞의 `+` 는 같이 지우고, `+` 로 시작하는 나라 밖 번호는
  8~15자리면 지운다.
- 한글로 읽은 숫자만 이어진 묶음은 7자 이상이고 (3자 이상 조각이 있거나 모두 한 자씩일 때) 지운다 — 「공사 일이 삼일 이상」
  처럼 두 자 낱말이 이어진 글은 남긴다.
- 지우지 않는 것: 날짜·시각·금액(천 단위 쉼표)·작업 id, 대표번호(15xx·16xx·18xx-xxxx — 사람 번호가 아니고 「1800-2000」
  같은 시각 범위와 모양이 같다), 앞뒤가 숫자인 긴 숫자(ID), 끝 4자리 같은 조각. 묶음 사이에 「에」 밖의 글자(다시·~·/)가
  끼면 이어 읽지 못한다(한계).

scrub — 비밀(키·Account ID: 원문·URL 인코딩·섞인 꼴, app.info.generic.scrub)을 지운 뒤 번호를 지운다.

HideSecrets·install — app.outreach·연락 프로그램·httpx 로거의 줄(메시지·예외 글·stack)을 scrub 한다. 로거 거르개는 자식
로거에 물려지지 않아(app.outreach.harness.gate 의 줄은 app.outreach 거르개를 거치지 않는다) LogRecord factory 에서 이름으로
걸러 건다. 이 모듈을 불러오면(app.outreach 를 불러오면) 번호 지우기는 켜지고, 키 목록은 install 이 준다. 비밀 목록을 읽지
못하면 그 줄을 HIDDEN_LINE 으로 바꾼다. secrets_provider 는 줄마다 불리므로 가벼워야 한다(메모리에 둔 값).
"""

import logging
import re
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass

from app.info import generic
from app.outreach.phone import _local, _parts

PHONE_MASK = "[번호]"
HIDDEN_LINE = "(비밀 목록을 읽지 못해 이 로그 줄을 숨겼습니다)"
LOGGERS = ("app.outreach", "app.programs.contacts", "app.programs.outreach", "app.programs.notify_settings",
           "app.tools.notify", "httpx")
SPOKEN_MIN = 7  # 한글로 읽은 숫자는 이만큼 이어지면 지운다
FOREIGN_MIN, MAX_DIGITS = 8, 15  # E.164 는 15자리까지
_MAX_GAP_MARKS = 3
_PLUS, _OPEN, _CLOSE = frozenset("+＋"), frozenset("(（"), frozenset(")）")
_SPOKEN = {"공": "0", "영": "0", "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5", "육": "6", "륙": "6", "칠": "7",
           "팔": "8", "구": "9"}
_TO_DIGITS = str.maketrans({**{chr(0xFF10 + i): str(i) for i in range(10)}, **_SPOKEN})
_TOKEN = re.compile(r"(?P<d>[0-9０-９]+)|(?P<k>(?:(?<![가-힣])|(?<=에))[공영일이삼사오육륙칠팔구]+)")
_GAP = re.compile(r"(?:\s|[-‐‑‒–—−－﹣.．()（）에]|[,，](?=\s))*")


@dataclass(frozen=True)
class _Tok:
    start: int
    end: int
    digits: str
    spoken: bool


def _joins(gap: str) -> bool:
    return bool(_GAP.fullmatch(gap)) and sum(not c.isspace() for c in gap) <= _MAX_GAP_MARKS


def _phone_shaped(parts: list[str], free: list[bool]) -> bool:
    """이어 붙인 숫자가 국내 번호 모양이고 조각 경계가 자리 경계에만 있는가. free[k] 는 k 뒤 경계를 보지 않는다(줄 바꿈)."""
    joined = "".join(parts)
    local, prefix = _local(joined)
    split = _parts(local)
    if split is None:
        return False
    if all(len(p) == 1 for p in parts):
        return True
    offset = prefix - (len(local) - (len(joined) - prefix))  # 0 을 붙였으면 한 칸 당긴다
    allowed = {offset + len(split[0]), offset + len(split[0]) + len(split[1])}
    if prefix:
        allowed.add(prefix)  # +82 | 10
        if offset == prefix:
            allowed.add(prefix + 1)  # +82 | (0) | 10
    cut, cuts = 0, []
    for k, part in enumerate(parts[:-1]):
        cut += len(part)
        if not free[k]:
            cuts.append(cut)
    return all(c in allowed for c in cuts)


def _window(text: str, run: list[_Tok], i: int) -> int | None:
    """run[i] 에서 시작해 지울 가장 긴 묶음의 끝 j. 없으면 None."""
    plus = run[i].start > 0 and text[run[i].start - 1] in _PLUS
    if not plus and run[i].digits[0] not in "08":
        return None  # 국내 번호는 0, 나라 앞머리는 82·0082 로 시작한다
    foreign = None
    for j in range(min(len(run), i + MAX_DIGITS) - 1, i - 1, -1):
        parts = [t.digits for t in run[i:j + 1]]
        size = sum(map(len, parts))
        if size > MAX_DIGITS:
            continue
        free = [bool(re.search(r"[\r\n]", text[a.end:b.start])) for a, b in zip(run[i:j], run[i + 1:j + 1])]
        if _phone_shaped(parts, free):
            return j
        if plus and foreign is None and size >= FOREIGN_MIN:
            foreign = j
    return foreign


def _run_spans(text: str, run: list[_Tok]) -> list[tuple[int, int]]:
    spans, used, i = [], [False] * len(run), 0
    while i < len(run):
        j = _window(text, run, i)
        if j is None:
            i += 1
            continue
        start = run[i].start
        before = text[start - 1] if start else ""
        first_gap = text[run[i].end:run[i + 1].start] if j > i else ""
        if before in _PLUS or (before in _OPEN and any(c in _CLOSE for c in first_gap)):
            start -= 1
        spans.append((start, run[j].end))
        used[i:j + 1] = [True] * (j + 1 - i)
        i = j + 1
    group: list[_Tok] = []
    for tok, done in [*zip(run, used), (None, True)]:  # 끝 표시로 마지막 묶음도 본다
        if tok is not None and tok.spoken and not done:
            group.append(tok)
            continue
        sizes = [len(t.digits) for t in group]
        if sum(sizes) >= SPOKEN_MIN and (max(sizes) >= 3 or max(sizes) == 1):
            spans.append((group[0].start, group[-1].end))
        group = []
    return spans


def hide_phones(text: str) -> str:
    """번호처럼 보이는 것(모듈 머리 글)을 `[번호]` 로."""
    spans: list[tuple[int, int]] = []
    run: list[_Tok] = []
    for m in _TOKEN.finditer(text):
        tok = _Tok(m.start(), m.end(), m.group().translate(_TO_DIGITS), m.group("k") is not None)
        if run and not _joins(text[run[-1].end:tok.start]):
            spans += _run_spans(text, run)
            run = []
        run.append(tok)
    spans += _run_spans(text, run)
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + PHONE_MASK + text[end:]
    return text


def scrub(text: str, secrets: Iterable[str]) -> str:
    """비밀(키·Account ID — 원문·URL 인코딩·섞인 꼴)과 번호를 지운다. 빈 비밀은 건너뛴다."""
    for secret in secrets:
        if secret:
            text = generic.scrub(text, secret)
    return hide_phones(text)


_READING: ContextVar[bool] = ContextVar("redact_reading_secrets", default=False)


class HideSecrets(logging.Filter):
    """로그 줄(메시지·예외 글·stack)에서 secrets_provider() 의 비밀과 번호를 지운다. 줄은 늘 남긴다(True)."""

    def __init__(self, secrets_provider: Callable[[], list[str]]) -> None:
        super().__init__()
        self._secrets_provider = secrets_provider

    def _secrets(self) -> list[str] | None:
        if _READING.get():  # 비밀 목록을 읽다가 남긴 줄 — 번호만 지운다
            return []
        token = _READING.set(True)
        try:
            return list(self._secrets_provider())
        except Exception:  # noqa: BLE001 — 목록을 못 읽으면 줄을 숨긴다(아래)
            return None
        finally:
            _READING.reset(token)

    def filter(self, record: logging.LogRecord) -> bool:
        secrets = self._secrets()

        def clean(text: str) -> str:
            return HIDDEN_LINE if secrets is None else scrub(text, secrets)

        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 — 형식이 틀린 줄: 인자는 버리고 틀만 남긴다
            text = str(record.msg)
        record.msg, record.args = clean(text), ()
        if record.exc_info:
            record.exc_text = record.exc_text or logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = clean(record.exc_text)
        if record.stack_info:
            record.stack_info = clean(record.stack_info)
        return True


_FILTER: HideSecrets | None = None
_BASE_FACTORY: Callable[..., logging.LogRecord] | None = None


def _covered(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in LOGGERS)


def _make_record(*args, **kwargs) -> logging.LogRecord:
    record = _BASE_FACTORY(*args, **kwargs)
    if _FILTER is not None and _covered(record.name):
        _FILTER.filter(record)
    return record


def install(secrets_provider: Callable[[], list[str]]) -> None:
    """LOGGERS(아래 로거 모두)의 줄을 이 비밀 목록으로 지운다. 다시 부르면 목록만 바꾼다."""
    global _FILTER, _BASE_FACTORY
    _FILTER = HideSecrets(secrets_provider)
    if _BASE_FACTORY is None:
        _BASE_FACTORY = logging.getLogRecordFactory()
        logging.setLogRecordFactory(_make_record)


install(list)  # 키 목록 없이 번호만
