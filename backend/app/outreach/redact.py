"""번호와 키 지우기: 모델 프롬프트·도구 결과·trace·로그·오류 글로 나가기 전에 거치는 한 곳.

hide_phones — 번호처럼 보이는 것을 `[번호]` 로.
- 읽기 전에 폭 없는 글자(U+200B~D·U+2060·U+FEFF·U+00AD)는 빼고, %20·%2D·%2E·%2B 는 빈칸·줄표·점·+ 로 읽는다(지울 때는
  원래 글의 자리로 돌려 지운다).
- 숫자 묶음(반각·전각)과 한글로 읽은 숫자 묶음(공·영·일·이·삼·사·오·육·륙·칠·팔·구 — 낱말 가운데서 시작하지 않는 것,
  「에」 뒤는 된다)을 조각(token)으로 읽고, 사이가 빈칸·줄 바꿈·줄표·점·괄호·/ ／ · ・ _ ~·「쉼표+빈칸」·에·하고·다시(번호를
  소리 내어 읽을 때 줄표 자리)뿐이면 한 줄기로 잇는다. 쉼표 바로 뒤에 숫자가 오면(1,020,000) 천 단위 쉼표로 보고 잇지 않는다.
  사이에 빈칸 아닌 구분은 3개까지.
- 줄기 안에서 앞에서부터 「이어 붙인 숫자가 국내 번호 모양(phone._parts, `+82`·`82`·`0082` 앞머리 포함)이고, 조각의 경계가
  번호의 자리 경계(앞자리|가운데|끝 4자리, 나라 앞머리, `(0)`)에만 있는」 가장 긴 조각 묶음을 지운다. 경계를 보기 때문에
  날짜 목록(2026-02-01, 2026-02-02)이 번호로 잘못 이어지지 않는다. 경계를 보지 않는 것: 줄 바꿈이 있는 경계(줄이 바뀌며 묶음
  가운데가 나뉜 꼴), 한 자씩 띄운 꼴(0 1 0 …), 11자리 휴대전화(010-00-00-0199 — 날짜·시각 조각은 2·4자리라 11자리가 되지
  않는다). 지역 번호(02·0xx)는 국번이 2~9 로 시작해야 번호로 본다(「02 0900-1800」은 시각). 바로 앞의 `+` 는 같이 지우고,
  `+` 로 시작하는 나라 밖 번호는 8~15자리면 지운다.
- 한글로 읽은 숫자만 이어진 묶음은 7자 이상이고 (3자 이상 조각이 있거나 모두 한 자씩일 때) 지운다 — 「공사 일이 삼일 이상」
  처럼 두 자 낱말이 이어진 글은 남긴다.
- 지우지 않는 것: 날짜·시각·금액(천 단위 쉼표)·좌표·작업 id, 대표번호(15xx·16xx·18xx-xxxx — 자유 글에서는 「1800-2000」
  같은 시각 범위와 모양이 같아 남긴다. phone.normalize 는 대표번호를 받는다), 앞뒤가 숫자인 긴 숫자(ID), 끝 4자리 같은 조각.
- 줄기마다 시작 조각에서 맞을 수 있는 길이(앞자리로 정해지는 두 가지)만 보므로 글 길이에 비례한다.

scrub — 비밀(키·Account ID: 원문·URL 인코딩·섞인 꼴, app.info.generic.scrub)을 지운 뒤 번호를 지운다. SecretStr 은 값을
꺼내 쓰고, 글이 아니거나 8자보다 짧은 비밀은 건너뛴다(짧은 값을 지우면 보통 글이 망가진다).

HideSecrets·install·activate — LOGGERS(아래 로거 모두)의 줄(메시지·예외 글·stack·extra 칸)을 scrub 한다. 로거 거르개는 자식
로거에 물려지지 않아 LogRecord factory 에서 이름으로 걸러 건다(activate — 여러 번 불러도, 모듈을 다시 불러와도 한 겹).
logging.makeLogRecord 로 만든 줄(이름이 뒤에 붙음)은 메시지를 꺼낼 때 지운다. 이 모듈을 불러오면 번호 지우기가 켜지고, 앱도
뜰 때 activate 를 부른다. 키 목록은 install 이 준다. 거르는 도중 무엇이 실패해도(비밀 목록을 못 읽음 포함) 로그를 남긴 코드로
올라가지 않고 그 줄을 HIDDEN_LINE 으로 바꾼다. secrets_provider 는 줄마다 불리므로 가벼워야 한다(메모리에 둔 값).
"""

import logging
import re
import threading
from collections.abc import Callable, Iterable
from contextvars import ContextVar

from app.info import generic
from app.outreach.phone import AREA, FORMAT_CHARS, _local, _parts

PHONE_MASK = "[번호]"
HIDDEN_LINE = "(비밀 목록을 읽지 못해 이 로그 줄을 숨겼습니다)"
LOGGERS = ("app.outreach", "app.programs.contacts", "app.programs.outreach", "app.programs.notify_settings",
           "app.tools.notify", "app.notify", "app.errors", "uvicorn.error", "httpx", "httpcore")
MIN_SECRET = 8
SPOKEN_MIN = 7  # 한글로 읽은 숫자는 이만큼 이어지면 지운다
FOREIGN_MIN, MAX_DIGITS = 8, 15  # E.164 는 15자리까지
_PLUS, _OPEN, _CLOSE = frozenset("+＋"), frozenset("(（"), frozenset(")）")
_SPOKEN = {"공": "0", "영": "0", "일": "1", "이": "2", "삼": "3", "사": "4", "오": "5", "육": "6", "륙": "6", "칠": "7",
           "팔": "8", "구": "9"}
_TO_DIGITS = str.maketrans({**{chr(0xFF10 + i): str(i) for i in range(10)}, **_SPOKEN})
_PRE = re.compile("%(?:20|2[DdEeBb])|[" + FORMAT_CHARS + "]")
_ESCAPES = {"%20": " ", "%2D": "-", "%2E": ".", "%2B": "+"}
_K = "".join(_SPOKEN)
_TOK = rf"(?:[0-9０-９]+|(?:(?<![가-힣])|(?<=에))[{_K}]+)"
_MARK = r"(?:[-‐‑‒–—−－﹣.．()（）/／·・_~에]|하고|다시|[,，](?=\s))"
_RUN = re.compile(rf"{_TOK}(?:\s*(?:{_MARK}\s*){{0,3}}{_TOK})*")
_TOKEN = re.compile(rf"(?P<d>[0-9０-９]+)|(?P<k>(?:(?<![가-힣])|(?<=에))[{_K}]+)")
_LINE_BREAK = re.compile(r"[\r\n]")


def _prepared(text: str) -> tuple[str, list[int] | None, list[int] | None]:
    """(읽을 글, 읽을 글 자리 → 원래 글 시작 자리, → 원래 글 끝 자리). 바꿀 것이 없으면 (원래 글, None, None)."""
    if not _PRE.search(text):
        return text, None, None
    out, starts, ends, pos, dropped = [], [], [], 0, None  # dropped: 빠진 폭 없는 글자의 시작(다음 글자에 붙인다)

    def keep(a: int, b: int) -> None:
        nonlocal dropped
        if a < b:
            out.append(text[a:b])
            starts.extend(range(a, b))
            ends.extend(range(a + 1, b + 1))
            if dropped is not None:
                starts[-(b - a)], dropped = dropped, None

    for m in _PRE.finditer(text):
        keep(pos, m.start())
        if m.group().startswith("%"):
            out.append(_ESCAPES[m.group().upper()])
            starts.append(m.start() if dropped is None else dropped)
            ends.append(m.end())
            dropped = None
        elif dropped is None:
            dropped = m.start()
        pos = m.end()
    keep(pos, len(text))
    return "".join(out), starts, ends


def _lengths(digits: str) -> list[int]:
    """digits 앞에서 시작하는 국내 번호가 차지할 수 있는 숫자 길이(긴 것부터). 앞자리로 정해진다."""
    local, prefix = _local(digits)
    m = AREA.match(local)
    if m is None:
        return []
    added = len(local) - (len(digits) - prefix)  # 0 을 붙였으면 1
    return [prefix - added + len(m.group()) + middle + 4 for middle in (4, 3)]


def _phone_shaped(parts: list[str], free: list[bool], *, relaxed: bool) -> bool:
    """이어 붙인 숫자가 국내 번호 모양이고 조각 경계가 자리 경계에만 있는가. free[k] 는 k 뒤 경계를 보지 않는다(줄 바꿈).
    relaxed 면 경계를 보지 않는 두 꼴도 받는다: 한 자씩 띄운 꼴(0 으로 시작), 첫 조각이 01x 를 다 품은 11자리 휴대전화
    (010 0000 01 99). 맨 82(+ 없이)로 시작하면 받지 않는다 — 날짜 목록(8/21 …)이 그렇게 시작한다."""
    joined = "".join(parts)
    local, prefix = _local(joined)
    split = _parts(local, rep=False)
    if split is None:
        return False
    if len(parts) == 1:
        return True
    if split[0].startswith("050") and len(split[1]) == 4:
        return False  # 4-4-4 로 나뉜 050x 는 호실 목록(0502·0503·0504호)과 모양이 같다 — 붙여 쓴 꼴만 지운다
    if relaxed and not prefix and (all(len(p) == 1 for p in parts) or (
            split[0].startswith("01") and len(local) == 11 and parts[0].startswith(split[0]))):
        return True
    offset = prefix - (len(local) - (len(joined) - prefix))  # 0 을 붙였으면 한 칸 당긴다
    allowed = {offset + len(split[0]), offset + len(split[0]) + len(split[1])}
    if prefix:
        allowed.add(prefix)  # +82 | 10
        if offset == prefix:
            allowed.add(prefix + 1)  # +82 | (0) | 10
    cut = 0
    for k, part in enumerate(parts[:-1]):
        cut += len(part)
        if not free[k] and cut not in allowed:
            return False
    return True


class _Run:
    """한 줄기의 조각들. 자리는 읽을 글 기준."""

    def __init__(self, scan: str, start: int, end: int) -> None:
        self.scan = scan
        self.starts, self.ends, self.digits, self.spoken = [], [], [], []
        for t in _TOKEN.finditer(scan, start, end):
            self.starts.append(t.start())
            self.ends.append(t.end())
            self.digits.append(t.group().translate(_TO_DIGITS))
            self.spoken.append(t.group("k") is not None)
        self.joined = "".join(self.digits)
        self.cum = [0]
        for d in self.digits:
            self.cum.append(self.cum[-1] + len(d))
        self.at = {c: k for k, c in enumerate(self.cum)}

    def _shaped(self, i: int, j: int, relaxed: bool) -> bool:
        free = [bool(_LINE_BREAK.search(self.scan, self.ends[k], self.starts[k + 1])) for k in range(i, j)]
        return _phone_shaped(self.digits[i:j + 1], free, relaxed=relaxed)

    def window(self, i: int, relaxed: bool, stop: int) -> int | None:
        """조각 i 에서 시작해(조각 stop 앞까지) 지울 가장 긴 묶음의 끝 j. 없으면 None."""
        c = self.cum[i]
        plus = self.starts[i] > 0 and self.scan[self.starts[i] - 1] in _PLUS
        head = self.joined[c:c + MAX_DIGITS]
        if not plus and not (head[0] == "0" and (head[1:2] != "0" or head.startswith("0082")) or head.startswith("82")):
            return None  # 국내 번호는 0(00 은 0082 만), 나라 앞머리는 82 로 시작한다
        for length in _lengths(head):
            k = self.at.get(c + length)
            if k is not None and i < k <= stop and self._shaped(i, k - 1, relaxed):
                return k - 1
        if plus and not relaxed:
            for length in range(min(MAX_DIGITS, len(self.joined) - c), FOREIGN_MIN - 1, -1):
                k = self.at.get(c + length)
                if k is not None and i < k <= stop:
                    return k - 1
        return None

    def _pass(self, out: list[tuple[int, int]], used: list[bool], relaxed: bool) -> None:
        """남은 조각에서 앞에서부터 묶음을 찾아 지운다. 이미 지운 조각을 넘지 않는다."""
        i, n = 0, len(self.digits)
        nxt = [n] * (n + 1)  # nxt[k]: k 부터 처음 지운 조각(이 판에서 새로 지우는 것은 늘 i 뒤가 아니다)
        for k in range(n - 1, -1, -1):
            nxt[k] = k if used[k] else nxt[k + 1]
        while i < n:
            j = None if used[i] else self.window(i, relaxed, nxt[i])
            if j is None:
                i += 1
                continue
            start = self.starts[i]
            before = self.scan[start - 1] if start else ""
            first_gap = self.scan[self.ends[i]:self.starts[i + 1]] if j > i else ""
            if before in _PLUS or (before in _OPEN and any(c in _CLOSE for c in first_gap)):
                start -= 1
            out.append((start, self.ends[j]))
            used[i:j + 1] = [True] * (j + 1 - i)
            i = j + 1

    def spans(self) -> list[tuple[int, int]]:
        """자리 경계가 맞는 번호를 먼저(고쳐 부른 받아쓰기에서 번호 전체를 덮는 쪽), 그다음 경계를 보지 않는 꼴."""
        out: list[tuple[int, int]] = []
        used, n = [False] * len(self.digits), len(self.digits)
        self._pass(out, used, relaxed=False)
        self._pass(out, used, relaxed=True)
        group: list[int] = []
        for k in [*range(n), None]:  # 끝 표시로 마지막 묶음도 본다
            if k is not None and self.spoken[k] and not used[k]:
                group.append(k)
                continue
            sizes = [len(self.digits[g]) for g in group]
            if sum(sizes) >= SPOKEN_MIN and (max(sizes) >= 3 or max(sizes) == 1):
                out.append((self.starts[group[0]], self.ends[group[-1]]))
            group = []
        return out


def hide_phones(text: str) -> str:
    """번호처럼 보이는 것(모듈 머리 글)을 `[번호]` 로. 지운 번호 바로 앞의 폭 없는 글자도 같이 지운다."""
    scan, starts, ends = _prepared(text)
    spans = [span for m in _RUN.finditer(scan) for span in _Run(scan, m.start(), m.end()).spans()]
    if starts is not None:
        spans = [(starts[a], ends[b - 1]) for a, b in spans]
    pieces, pos = [], 0
    for a, b in sorted(spans):
        pieces += [text[pos:a], PHONE_MASK]
        pos = b
    return "".join(pieces) + text[pos:]


def _usable(secrets: Iterable[object]) -> list[str]:
    out = []
    for secret in secrets:
        if hasattr(secret, "get_secret_value"):
            secret = secret.get_secret_value()
        if isinstance(secret, str) and len(secret) >= MIN_SECRET:
            out.append(secret)
    return out


# add_secrets 로 등록한 비밀(프로세스 전체, 더하기만). install·activate·모듈 다시 불러오기에 밀려나지 않는다.
_REGISTERED: set[str] = globals().get("_REGISTERED", set())
_REGISTERED_LOCK: threading.Lock = globals().get("_REGISTERED_LOCK", threading.Lock())


def add_secrets(*values: object) -> None:
    """비밀(키·Account ID …)을 더한다. 글·SecretStr 만, 8자보다 짧은 값은 버린다(scrub 과 같은 규칙). 같은 값은 한 번."""
    usable = _usable(values)
    with _REGISTERED_LOCK:
        _REGISTERED.update(usable)


def forget_secrets() -> None:
    """등록한 비밀을 모두 비운다 — 시험 전용(tests/outreach_doubles 의 autouse 고정물이 시험마다 부른다)."""
    with _REGISTERED_LOCK:
        _REGISTERED.clear()


def _registered() -> list[str]:
    with _REGISTERED_LOCK:
        return list(_REGISTERED)


def _ordered(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda v: (-len(v), v)))  # 긴 것부터(겹치는 값이 덜 남게)


def secrets() -> tuple[str, ...]:
    """지금 쓰는 비밀 전체: add_secrets 로 등록한 값 + install 원천이 주는 값. 다른 모듈이 비밀 목록을 읽는 단 하나의 길.
    install 원천이 실패하면 그 예외가 그대로 올라간다(부르는 쪽이 「읽지 못함」으로 다룬다)."""
    source = _FILTER._secrets_provider() if _FILTER is not None else []
    return _ordered([*_registered(), *_usable(source)])


def scrub(text: str, secrets: Iterable[str]) -> str:
    """비밀(주어진 것 + add_secrets 로 등록한 것 — 원문·URL 인코딩·섞인 꼴)과 번호를 지운다.
    8자보다 짧거나 글이 아닌 비밀은 건너뛴다."""
    for secret in _ordered([*_registered(), *_usable(secrets)]):
        text = generic.scrub(text, secret)
    return hide_phones(text)


_READING: ContextVar[bool] = ContextVar("redact_reading_secrets", default=False)
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime", "_redacted"}


def _clean_value(value: object, clean: Callable[[str], str], depth: int = 3) -> object:
    """글은 지우고, dict·list·tuple 은 세 겹까지 들어간다. 그 밖의 물건은 그대로 둔다(__str__ 을 부르지 않는다)."""
    if isinstance(value, str):
        return clean(value)
    if depth == 0:
        return value
    if isinstance(value, dict):
        return {k: _clean_value(v, clean, depth - 1) for k, v in value.items()}
    if type(value) in (list, tuple):
        return type(value)(_clean_value(v, clean, depth - 1) for v in value)
    return value


class HideSecrets(logging.Filter):
    """로그 줄(메시지·예외 글·stack·extra 칸)에서 비밀(add_secrets 로 등록한 것 + secrets_provider() 의 것)과 번호를
    지운다. 줄은 늘 남긴다(True)."""

    def __init__(self, secrets_provider: Callable[[], list[str]]) -> None:
        super().__init__()
        self._secrets_provider = secrets_provider

    def _secrets(self) -> list[str] | None:
        if _READING.get():  # 비밀 목록을 읽다가 남긴 줄 — 번호만 지운다
            return []
        token = _READING.set(True)
        try:
            return _usable(self._secrets_provider())
        except Exception:  # noqa: BLE001 — 목록을 못 읽으면 줄을 숨긴다
            return None
        finally:
            _READING.reset(token)

    def filter(self, record: logging.LogRecord) -> bool:
        self._guarded(record, extras_only=False)
        return True

    def clean_extras(self, record: logging.LogRecord) -> None:
        """extra 칸만(LogRecord 의 기본 칸이 아닌 것 — 글, dict·list 는 한 겹) 지운다. 없으면 비밀 목록도 읽지 않는다."""
        if any(key not in _STANDARD for key in record.__dict__):
            self._guarded(record, extras_only=True)

    def _guarded(self, record: logging.LogRecord, *, extras_only: bool) -> None:
        try:
            self._clean(record, extras_only)
        except Exception:  # noqa: BLE001 — 어떤 실패도 로그를 남긴 코드로 올리지 않는다
            record.msg, record.args = HIDDEN_LINE, ()
            record.exc_info = record.exc_text = record.stack_info = None
            for key in [key for key in record.__dict__ if key not in _STANDARD]:
                record.__dict__[key] = HIDDEN_LINE

    def _clean(self, record: logging.LogRecord, extras_only: bool) -> None:
        secrets = self._secrets()

        def clean(text: str) -> str:
            return HIDDEN_LINE if secrets is None else scrub(text, secrets)

        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD:
                record.__dict__[key] = _clean_value(value, clean)
        if extras_only:
            return
        try:
            text = logging.LogRecord.getMessage(record)
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


_FILTER: HideSecrets | None = globals().get("_FILTER")  # 모듈을 다시 불러와도(reload) 비밀 목록을 잃지 않는다
_BASE_FACTORY: Callable[..., logging.LogRecord] | None = globals().get("_BASE_FACTORY")
_MAKING: ContextVar[bool] = globals().get("_MAKING") or ContextVar("redact_making_record", default=False)
_PROBE: ContextVar[list | None] = globals().get("_PROBE") or ContextVar("redact_factory_probe", default=None)
_ORIGINAL_MAKE = getattr(logging.Logger.makeRecord, "_redact_original", logging.Logger.makeRecord)


def _covered(name: object) -> bool:
    return isinstance(name, str) and any(name == p or name.startswith(p + ".") for p in LOGGERS)


class _LateRecord(logging.LogRecord):
    """logging.makeLogRecord 의 줄(이름·메시지가 만든 뒤에 붙는다) — 메시지를 꺼낼 때 지운다."""

    def getMessage(self) -> str:
        if not self.__dict__.get("_redacted") and _FILTER is not None and _covered(self.name):
            self._redacted = True
            _FILTER.filter(self)
        return super().getMessage()


def _make_record(*args, **kwargs) -> logging.LogRecord:
    probe = _PROBE.get()
    if probe is not None:  # activate 가 지금 factory 가 우리를 거치는지 보는 중
        probe.append(True)
        return logging.LogRecord(*args, **kwargs)
    if (args[0] if args else kwargs.get("name")) is None:
        return _LateRecord(*args, **kwargs)
    base = _BASE_FACTORY
    if _MAKING.get() or base is None:  # 남의 factory 가 우리를 감싸 다시 불렀다 — 고리를 끊고 맨 줄을 준다
        return logging.LogRecord(*args, **kwargs)
    token = _MAKING.set(True)
    try:
        record = base(*args, **kwargs)
    finally:
        _MAKING.reset(token)  # 지우는 동안(비밀 목록을 읽다 남긴 줄)은 다시 거른다
    if _FILTER is not None and _covered(record.name):
        _FILTER.filter(record)
    return record


def _make_with_extras(self: logging.Logger, *args, **kwargs) -> logging.LogRecord:
    """Logger.makeRecord 는 factory 뒤에 extra 칸을 붙인다 — 그 칸을 줄을 만들 때 지운다."""
    record = _ORIGINAL_MAKE(self, *args, **kwargs)
    if _FILTER is not None and _covered(record.name):
        _FILTER.clean_extras(record)
    return record


_make_with_extras._redact_original = _ORIGINAL_MAKE


def _leads_to_us(factory: Callable[..., logging.LogRecord]) -> bool:
    """factory 가 (남이 감싸) 이미 우리 factory 를 거치는가 — 한 번 불러 본다."""
    seen: list = []
    token = _PROBE.set(seen)
    try:
        factory("app.outreach.redact.probe", logging.DEBUG, __file__, 0, "", (), None)
    except Exception:  # noqa: BLE001 — 남의 factory 가 시험 호출을 못 받으면 거치지 않는다고 본다
        return bool(seen)
    finally:
        _PROBE.reset(token)
    return bool(seen)


def activate() -> None:
    """LogRecord factory(와 Logger.makeRecord)에 거르개를 건다. 여러 번 불러도, 모듈을 다시 불러와도(reload) 한 겹이고,
    남의 factory 가 이미 우리를 감싸고 있으면 그대로 둔다(그것을 밑으로 삼으면 서로 부르다 RecursionError)."""
    global _BASE_FACTORY
    current_make = logging.Logger.makeRecord
    if current_make is not _make_with_extras and (
            current_make is _ORIGINAL_MAKE or hasattr(current_make, "_redact_original")):
        logging.Logger.makeRecord = _make_with_extras
    current = logging.getLogRecordFactory()
    if current is _make_record:
        return
    base = getattr(current, "_redact_base", None)  # 다시 불러온 이 모듈의 옛 factory 면 그 밑을 쓴다
    if base is None:
        if _leads_to_us(current):
            return
        base = current
    _BASE_FACTORY = base
    _make_record._redact_base = base
    logging.setLogRecordFactory(_make_record)


def install(secrets_provider: Callable[[], list[str]]) -> None:
    """LOGGERS 의 줄을 지울 비밀 원천(하나)을 정한다. 다시 부르면 원천만 바꾼다 — add_secrets 로 등록한 값은 그대로 남는다."""
    global _FILTER
    _FILTER = HideSecrets(secrets_provider)
    activate()


if _FILTER is None:
    install(list)  # 키 목록 없이 번호만
else:
    activate()
