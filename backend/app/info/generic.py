"""범용 정보 API(관리자가 주소·키·설명을 넣은 공공데이터 연결): GET 한 번, 안전 검사, 키 지우기, XML → JSON 꼴.

- GET 만, 리다이렉트는 따라가지 않는다(3xx 는 실패). 이름 풀이를 포함해 전체 15초. 본문은 날 바이트로 읽고 gzip·deflate 는
  zlib 의 max_length 로 300KB 를 넘게 풀지 않는다(그 밖의 Content-Encoding 은 실패).
- 경로는 / 로 시작하는 상대 경로만(request_problem). 만든 주소의 scheme·host·port 가 연결 주소와 같은지 다시 맞춘다.
- 주소(base_url_problem): http(s) 만, localhost·내부망 IP 꼴 거절. 부를 때는 호스트를 RESOLVE 로 풀어 모든 IP 가
  공인일 때만 연결한다(시험은 RESOLVE 를 바꿔 끼운다). http:// 는 확인한 IP 로 붙고 Host 머리글에 원래 이름을 단다
  (다시 풀어 내부망으로 바뀌는 것을 막는다). https:// 는 인증서 확인이 이름을 지킨다.
- 키: 질의(key_in query)면 연결의 key_name 그대로(대소문자 유지), 기상청과 같은 규칙으로 인코딩 키(% 있음)는 그대로,
  디코딩 키는 한 번만 인코딩한다. 머리글(header)이면 `key_name: 키`. 경로 질의·params 에 같은 이름(대소문자 무시)이 오면 거절.
- 이 함수 밖으로 나가는 것(본문·Content-Type·오류·주소·로그)에서 키를 지운다(scrub — 글자마다 그대로·%XX·%25XX·&#..;·
  \\u00XX 꼴, key_name 질의 값). 지운 뒤에도 풀어 보아(html·%·\\u) 키가 남으면 본문을 통째로 버린다(KEY_IN_BODY).
  예외 글은 담지 않고 종류만 code 로 바꾼다. httpx 요청 기록 줄은 _HideKey 가 지운다.
- 공공데이터포털 게이트웨이 오류(OpenAPI_ServiceResponse/cmmMsgHeader, JSON·XML)는 기상청과 같은 표(kma)로 읽고,
  메시지의 「기상청」을 연결 이름으로 바꿔 쓴다. 응답 머리(resultCode)는 부를 때는 읽지 않고(본문 그대로 에이전트가 읽는다)
  연결 시험만 계정 오류(20~22·30~33)를 본다(result_code_failure).
- XML 은 표준 라이브러리로만 바꾼다. DTD(<!DOCTYPE·<!ENTITY)가 있으면 바꾸지 않고(엔터티를 풀지 않는다) 깊이·마디 수를 막는다.
"""

import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlencode

import httpx

from app.info import kma

logger = logging.getLogger(__name__)

TIMEOUT_S = 15.0
MAX_BYTES = 300 * 1024  # 본문은 여기까지만 읽는다
BODY_LIMIT = 3500  # 에이전트에게 주는 본문: JSON 글로 옮긴 길이(따옴표·역빗금 포함)
SAMPLE_LIMIT = 300  # 연결 시험·실패에 보이는 본문 앞부분
CONTENT_TYPE_LIMIT = 100
TRUNCATED_HINT = " …(뒤는 생략 — 범위를 좁혀 다시 부르세요)"
MAX_XML_DEPTH = 50
MAX_XML_NODES = 20_000
MASK = "[키지움]"  # 빈칸이 없어야 key_name 값 지우기가 이 글 가운데서 멈추지 않는다
KEY_IN_BODY = "(응답에 키로 보이는 값이 남아 있어 본문을 보이지 않습니다 — 서버가 키를 되돌려 보낸 것 같습니다.)"
KEY_NAME_PATTERN = r"^[A-Za-z0-9_.\-]{1,60}$"  # 질의 이름·머리글 이름으로 그대로 쓸 수 있는 꼴
# 머리글 방식에서 키 이름으로 쓸 수 없는 이름(요청 틀·연결·압축·쿠키를 바꾼다). 소문자로 견준다.
FORBIDDEN_KEY_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "te", "upgrade",
                                   "expect", "accept-encoding", "cookie"})

# 시험이 가짜 transport 를 바꿔 끼운다.
TRANSPORT: httpx.AsyncBaseTransport | None = None

BAD_START = "path 는 / 로 시작하는 상대 경로만 됩니다(예: /getRestDeInfo)."
BAD_PART = "path 에 「{part}」는 쓸 수 없습니다 — 연결 주소 밖으로 나가는 경로는 부르지 않습니다."
KEY_PARAM = "키 이름({name})은 path·params 에 넣지 마세요 — 키는 코드가 붙입니다."
BAD_SCHEME = "주소는 http:// 또는 https:// 로 시작해야 합니다."
INTERNAL_HOST = "localhost 나 내부망(사설·루프백·링크로컬·멀티캐스트) 주소는 정보 API 주소로 쓸 수 없습니다."
RESOLVED_INTERNAL = "이 주소의 호스트가 내부망 IP 로 풀려 부르지 않았습니다."
OFF_BASE = "만든 주소가 연결 주소 밖이라 부르지 않았습니다."
BAD_URL_BUILD = "path·params 로 주소를 만들 수 없습니다(너무 길거나 쓸 수 없는 글자가 있습니다). 값을 줄이거나 고쳐 주세요."
KEY_HEADER = "머리글 「{name}」에는 키를 넣을 수 없습니다. 설정의 정보 API 연결에서 키 이름을 바꿔 주세요."
REDIRECT = "{name} 응답이 다른 주소로 넘기는 응답(HTTP {status})이라 따라가지 않았습니다(리다이렉트는 따르지 않습니다). 주소·경로를 확인해 주세요."
BAD_ENCODING = "{name} 응답이 풀 수 없는 압축 방식(Content-Encoding)으로 와서 읽지 않았습니다."
_FORBIDDEN = ("://", "..", "@", "\\", "#")
# 공인처럼 보이지만 안쪽 IPv4 를 품거나 옛 사이트 로컬인 IPv6(::/96 IPv4 호환·64:ff9b::/96 NAT64·fec0::/10)
_EMBEDDING_V6 = tuple(ipaddress.ip_network(n) for n in ("::/96", "64:ff9b::/96", "fec0::/10"))
_ACCOUNT_RESULT_CODES = frozenset({"20", "21", "22", "30", "31", "32", "33"})
_U_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_DOCTYPE = re.compile(r"<!\s*(DOCTYPE|ENTITY)", re.IGNORECASE)
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")


def _system_resolve(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


# 호스트 → IP 글 목록. 부를 때 스레드에서 부른다. 시험이 바꿔 끼운다.
RESOLVE: Callable[[str, int], list[str]] = _system_resolve


@dataclass(frozen=True)
class GenericConn:
    name: str
    base_url: str
    key: str  # 인코딩·디코딩 어느 쪽이든
    key_in: str  # 'query' | 'header'
    key_name: str


@dataclass(frozen=True)
class Fetched:
    http_status: int
    content_type: str
    text: str  # 본문 전체(JSON 글, XML 은 JSON 꼴 글, 그 밖은 받은 글). 키를 지웠다
    cut: bool  # MAX_BYTES 에서 읽기를 멈췄다
    url: str  # 부른 주소(키 없이)


class _Undecodable(Exception):
    """모르는 Content-Encoding."""


class GenericFailed(Exception):
    """불렀지만 실패했거나 부르지 않았다. message 는 한국어, 키·예외 글은 담지 않는다."""

    def __init__(self, code: str, message: str, http_status: int | None = None, sample: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.http_status, self.sample = code, message, http_status, sample


def failure_message(code: str, name: str) -> str:
    """기상청 연결과 같은 실패 글(kma.FAILED_MESSAGES)에서 「기상청」을 연결 이름으로."""
    return kma.FAILED_MESSAGES[code].replace("기상청", name)


# ── 검사 ────────────────────────────────────────────────────────────


def _same_name(a: str, b: str) -> bool:
    return a.casefold() == b.casefold()


def request_problem(path: str, params: dict[str, str], key_name: str) -> str | None:
    """path·params 가 안 되는 까닭(한국어) 또는 None. 부르기 전에 본다."""
    if path.startswith("//"):
        return BAD_PART.format(part="//")
    if not path.startswith("/"):
        return BAD_START
    if _CONTROL.search(path):
        return BAD_PART.format(part="제어 문자")
    if "%25" in path.split("?", 1)[0]:  # 경로 부분의 두 번 인코딩(%252e%252e 등). 질의 값은 된다
        return BAD_PART.format(part="%25")
    decoded = unquote(path)
    for part in _FORBIDDEN:
        if part in path or part in decoded:
            return BAD_PART.format(part=part)
    query = path.split("?", 1)[1] if "?" in path else ""
    names = [name for name, _ in parse_qsl(query, keep_blank_values=True)] + list(params)
    if any(_same_name(name, key_name) for name in names):
        return KEY_PARAM.format(name=key_name)
    return None


def _ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """IP 꼴 호스트면 그 주소(127.1·2130706433 같은 꼴도), 아니면 None. 이름 풀이는 하지 않는다."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


def _public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in _EMBEDDING_V6):
        return False
    return ip.is_global and not ip.is_multicast


def base_url_problem(base_url: str) -> str | None:
    """주소가 안 되는 까닭(한국어) 또는 None. 이름 풀이 없이 꼴만 본다(저장할 때·부를 때)."""
    try:
        url = httpx.URL(base_url)
    except httpx.InvalidURL:
        return BAD_SCHEME
    if url.scheme not in ("http", "https") or not url.host:
        return BAD_SCHEME
    host = url.host.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        return INTERNAL_HOST
    ip = _ip(host)
    if ip is not None and not _public(str(ip)):
        return INTERNAL_HOST
    return None


async def _resolved(url: httpx.URL, name: str) -> str | None:
    """호스트를 풀어 모든 IP 가 공인일 때만 지나가고 붙을 IP 하나를 돌려준다. IP 꼴이면 None(base_url_problem 이 봤다)."""
    if _ip(url.host) is not None:
        return None
    port = url.port or (443 if url.scheme == "https" else 80)
    addresses: list[str] | None = None
    try:
        addresses = await asyncio.to_thread(RESOLVE, url.host, port)
    except OSError:
        pass
    if addresses is None:
        raise GenericFailed("bad_url", failure_message("bad_url", name))
    if not addresses or not all(_public(a) for a in addresses):
        raise GenericFailed("blocked_host", RESOLVED_INTERNAL)
    return addresses[0]


# ── 키 ──────────────────────────────────────────────────────────────


def _char(c: str) -> str:
    """키 글자 하나가 응답에 나올 수 있는 꼴: 그대로·%XX·%25XX·&#NN;·&#xHH;·\\u00HH(+ 는 빈칸, / 는 \\/ 도)."""
    alts = {re.escape(c)}
    if ord(c) < 128:
        code = f"{ord(c):02x}"
        alts |= {f"%{code}", f"%25{code}", f"&#0*{ord(c)};", f"&#x0*{code};", rf"\\u00{code}"}
        if c == "+":
            alts.add(" ")
        if c == "/":
            alts.add(r"\\/")
    else:
        alts.add(re.escape(quote(c, safe="")))
    return "(?:" + "|".join(sorted(alts, key=len, reverse=True)) + ")"


def _key_pattern(key: str) -> str:
    """그대로의 키와 디코딩한 키, 둘 다 글자마다 섞인 꼴까지(대소문자는 re.IGNORECASE 로)."""
    return "|".join("".join(_char(c) for c in base) for base in sorted({key, unquote(key)}, key=len, reverse=True))


def key_survives(text: str, key: str) -> bool:
    """text 를 html·%·\\uXXXX 로 거듭 풀어 보아 키(그대로·디코딩)가 남아 있는가(대소문자 무시)."""
    plains = {p.casefold() for p in (key, unquote(key)) if p}
    current = text
    for _ in range(4):
        if any(p in current.casefold() for p in plains):
            return True
        current = unquote(html.unescape(_U_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), current)))
    return any(p in current.casefold() for p in plains)


def scrub(text: str, key: str, *, key_name: str | None = None) -> str:
    """text 에서 키(섞인 꼴까지, 대소문자 무시)와 key_name 질의 값(대소문자 무시)을 지운다."""
    if key:
        text = re.sub(_key_pattern(key), MASK, text, flags=re.IGNORECASE)
    if key_name:
        text = re.sub(rf"(?<![\w.\-])({re.escape(key_name)}=)[^&\s\"'<]*", rf"\g<1>{MASK}", text, flags=re.IGNORECASE)
    return text


# 지금 부르는 연결의 (key_name, 키). httpx 요청 기록 줄은 같은 작업(context) 안에서 남으므로 거기서 지운다.
_CURRENT: ContextVar[tuple[str, str] | None] = ContextVar("info_api_key", default=None)


class _HideKey(logging.Filter):
    """httpx 가 남기는 요청 줄(주소 포함)에서 지금 연결의 키와 key_name 질의 값을 지운다."""

    def filter(self, record: logging.LogRecord) -> bool:
        current = _CURRENT.get()
        if current is not None:
            text = record.getMessage()
            masked = scrub(text, current[1], key_name=current[0])
            if masked != text:
                record.msg, record.args = masked, ()
        return True


logging.getLogger("httpx").addFilter(_HideKey())


def _url(conn: GenericConn, path: str, params: dict[str, str], *, with_key: bool) -> httpx.URL:
    """연결 주소 + path(이미 인코딩된 질의는 그대로) + [키] + params(한 번 인코딩)."""
    parts = []
    if with_key and conn.key_in == "query":
        parts.append(f"{conn.key_name}={kma.encoded(conn.key)}")
    if params:
        parts.append(urlencode(params))
    raw = conn.base_url.rstrip("/") + path
    if parts:
        raw += ("&" if "?" in path else "?") + "&".join(parts)
    return httpx.URL(raw)


def _on_base(url: httpx.URL, base: httpx.URL) -> bool:
    prefix = base.path.rstrip("/") + "/"
    return (url.scheme, url.host, url.port) == (base.scheme, base.host, base.port) and url.path.startswith(prefix)


# ── 본문 ────────────────────────────────────────────────────────────


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _element(el: ET.Element, depth: int) -> object:
    if depth > MAX_XML_DEPTH:
        raise ValueError("XML 이 너무 깊습니다.")
    children = list(el)
    text = (el.text or "").strip()
    if not children and not el.attrib:
        return text
    out: dict[str, object] = {f"@{_local(k)}": v for k, v in el.attrib.items()}
    many: set[str] = set()
    for child in children:
        tag, value = _local(child.tag), _element(child, depth + 1)
        if tag not in out:
            out[tag] = value
        elif tag in many:
            out[tag].append(value)
        else:
            out[tag] = [out[tag], value]
            many.add(tag)
    if text:
        out["#text"] = text
    return out


def xml_to_data(text: str) -> dict:
    """XML 글 → {뿌리 이름: …}. 같은 이름이 여럿이면 목록, 속성은 "@이름", 섞인 글은 "#text". 안 되면 ValueError."""
    if _DOCTYPE.search(text):
        raise ValueError("DTD 가 있는 XML 은 읽지 않습니다.")
    try:
        root = ET.fromstring(_XML_DECL.sub("", text, count=1))
    except ET.ParseError:
        raise ValueError("XML 이 아닙니다.") from None
    if sum(1 for _ in root.iter()) > MAX_XML_NODES:
        raise ValueError("XML 마디가 너무 많습니다.")
    return {_local(root.tag): _element(root, 1)}


def _decode(raw: bytes, charset: str | None) -> str:
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _parse(text: str, content_type: str) -> object | None:
    """JSON 이면 그 값, XML 이면 JSON 꼴, 아니면 None."""
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        pass
    if "xml" in content_type.lower() or text.lstrip().startswith("<"):
        try:
            return xml_to_data(text)
        except (ValueError, RecursionError):
            return None
    return None


def gateway_code(data: object) -> str | None:
    """공공데이터포털 게이트웨이 오류 봉투면 code(kma 표), 아니면 None."""
    if not isinstance(data, dict) or not isinstance(data.get("OpenAPI_ServiceResponse"), dict):
        return None
    header = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader")
    reason = str((header if isinstance(header, dict) else {}).get("returnReasonCode") or "99").strip()
    return kma.REASONS.get(reason.zfill(2), "unknown")


def result_code_failure(text: str) -> str | None:
    """응답 머리 response.header.resultCode 가 계정 오류(20~22·30~33)면 code(kma 표), 아니면 None. 연결 시험만 쓴다."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    response = data.get("response") if isinstance(data, dict) else None
    header = response.get("header") if isinstance(response, dict) else None
    code = str(header.get("resultCode", "")).strip().zfill(2) if isinstance(header, dict) else ""
    return kma.REASONS.get(code) if code in _ACCOUNT_RESULT_CODES else None


def _json_len(text: str) -> int:
    return len(json.dumps(text, ensure_ascii=False))


def body_for_model(text: str, cut: bool) -> tuple[str, bool]:
    """(에이전트에게 줄 본문, 잘렸는가). JSON 글로 옮긴 길이가 BODY_LIMIT 안이다. 잘리면 끝에 TRUNCATED_HINT."""
    if not cut and _json_len(text) <= BODY_LIMIT:
        return text, False
    low, high = 0, min(len(text), BODY_LIMIT)
    while low < high:  # 옮긴 길이는 앞부분이 길수록 늘어난다 — 들어가는 가장 긴 앞부분
        mid = (low + high + 1) // 2
        if _json_len(text[:mid] + TRUNCATED_HINT) <= BODY_LIMIT:
            low = mid
        else:
            high = mid - 1
    return text[:low] + TRUNCATED_HINT, True


def _status_code(status: int, data: object) -> str | None:
    """실패 code 또는 None(2xx 이고 게이트웨이 오류가 아님). 게이트웨이 오류를 상태보다 먼저 본다(403 + 봉투)."""
    if 300 <= status < 400:
        return "redirect"
    if (gate := gateway_code(data)) is not None:
        return gate
    if status >= 500:
        return "server_error"
    if status >= 400 or status < 200:
        return kma.STATUS.get(status, "unknown")
    return None


def _decompressor(encoding: str, first: bytes) -> "zlib._Decompress | None":
    """Content-Encoding 에 맞는 zlib 풀개(없으면 None). deflate 는 zlib 머리가 있는지 첫 조각으로 가린다."""
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        wrapped = len(first) >= 2 and first[0] & 0x0F == 8 and ((first[0] << 8) | first[1]) % 31 == 0
        return zlib.decompressobj(zlib.MAX_WBITS if wrapped else -zlib.MAX_WBITS)
    raise _Undecodable


async def _read(response: httpx.Response) -> tuple[bytes, bool]:
    """날 바이트를 읽어(풀어서) MAX_BYTES 까지. (본문, MAX_BYTES 에서 멈췄는가). 푸는 쪽도 MAX_BYTES + 1 을 넘게 만들지 않는다."""
    encoding = response.headers.get("content-encoding", "").strip().lower()
    out = bytearray()
    decoder, started = None, False
    async for chunk in response.aiter_raw():
        if not started:
            decoder, started = _decompressor(encoding, chunk), True
        if decoder is not None:
            chunk = decoder.decompress(chunk, MAX_BYTES + 1 - len(out))
        out += chunk
        if len(out) > MAX_BYTES:
            return bytes(out[:MAX_BYTES]), True
    if not started:
        _decompressor(encoding, b"")  # 빈 본문이어도 모르는 압축이면 실패
    return bytes(out), False


def _clean(text: str, conn: GenericConn, dropped: str) -> str:
    """키를 지우고, 풀어 보아도 남으면 dropped 로 바꾼다."""
    text = scrub(text, conn.key, key_name=conn.key_name)
    return dropped if key_survives(text, conn.key) else text


# ── 부르기 ──────────────────────────────────────────────────────────


def _message(code: str, name: str, status: int | None = None) -> str:
    if code == "redirect":
        return REDIRECT.format(name=name, status=status)
    if code == "bad_encoding":
        return BAD_ENCODING.format(name=name)
    return failure_message(code, name)


def _target(conn: GenericConn, path: str, params: dict[str, str]) -> tuple[httpx.URL, httpx.URL, str]:
    """(연결 주소, 부를 주소, 보일 주소 — 키 없이). 안 되면 GenericFailed(bad_path·blocked_host). 부르기 전에 본다."""
    problem = request_problem(path, params, conn.key_name)
    if problem is not None:
        raise GenericFailed("bad_path", problem)
    if conn.key_in == "header" and conn.key_name.casefold() in FORBIDDEN_KEY_HEADERS:
        raise GenericFailed("bad_path", KEY_HEADER.format(name=conn.key_name))
    problem = base_url_problem(conn.base_url)
    if problem is not None:
        raise GenericFailed("blocked_host", problem)
    base = httpx.URL(conn.base_url)
    try:
        url = _url(conn, path, params, with_key=True)
        shown = scrub(str(_url(conn, path, params, with_key=False)), conn.key, key_name=conn.key_name)
    except (httpx.InvalidURL, ValueError):  # 예외 글에 주소(키)가 있을 수 있어 담지 않는다
        url = shown = None
    if url is None:
        raise GenericFailed("bad_path", BAD_URL_BUILD)
    if not _on_base(url, base):
        raise GenericFailed("bad_path", OFF_BASE)
    return base, url, shown


async def fetch(conn: GenericConn, path: str, params: dict[str, str]) -> Fetched:
    """연결 주소 + path 를 GET 으로 한 번 부른다. 2xx 이고 게이트웨이 오류가 아니면 Fetched, 아니면 GenericFailed."""
    base, url, shown = _target(conn, path, params)
    headers = {"Accept-Encoding": "identity"}
    if conn.key_in == "header":
        headers[conn.key_name] = conn.key
    code: str | None = None
    token = _CURRENT.set((conn.key_name, conn.key))
    try:
        async with asyncio.timeout(TIMEOUT_S):  # 이름 풀이도 이 안
            pinned = await _resolved(base, conn.name)
            if pinned is not None and url.scheme == "http":  # 확인한 IP 로 붙는다(다시 풀지 않는다)
                headers["Host"] = base.netloc.decode("ascii")
                url = url.copy_with(host=pinned)
            async with (
                httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_S, trust_env=False,
                                  follow_redirects=False) as http,
                http.stream("GET", url, headers=headers) as response,
            ):
                raw, cut = await _read(response)
                status = response.status_code
                content_type = response.headers.get("content-type", "")
                charset = response.charset_encoding
    except GenericFailed:
        raise
    except (httpx.TimeoutException, TimeoutError):
        code = "timeout"
    except _Undecodable:
        code = "bad_encoding"
    except httpx.HTTPError as exc:  # 예외 글에 주소(키)가 있을 수 있어 종류만 남긴다
        code = "bad_url" if isinstance(exc, httpx.ConnectError | httpx.UnsupportedProtocol) else "unknown"
    except Exception:  # noqa: BLE001 — 어떤 예외 글도 밖으로 내지 않는다(키가 있을 수 있다)
        code = "unknown"
    finally:
        _CURRENT.reset(token)
    if code is not None:
        logger.warning("정보 API 호출 실패: %s code=%s", conn.name, code)
        raise GenericFailed(code, _message(code, conn.name))
    text = _decode(raw, charset)
    data = _parse(text, content_type)
    text = _clean(text if data is None else json.dumps(data, ensure_ascii=False), conn, KEY_IN_BODY)
    content_type = _clean(content_type, conn, "")[:CONTENT_TYPE_LIMIT]
    code = _status_code(status, data)
    if code is not None:
        logger.warning("정보 API 호출 실패: %s code=%s status=%s", conn.name, code, status)
        raise GenericFailed(code, _message(code, conn.name, status), http_status=status, sample=text[:SAMPLE_LIMIT])
    return Fetched(http_status=status, content_type=content_type, text=text, cut=cut, url=shown)
