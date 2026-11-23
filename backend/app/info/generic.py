"""범용 정보 API(관리자가 주소·키·설명을 넣은 공공데이터 연결): GET 한 번, 안전 검사, 키 지우기, XML → JSON 꼴.

- GET 만, 리다이렉트는 따라가지 않는다(3xx 는 실패). 전체 15초, 본문은 300KB 까지만 읽고 멈춘다.
- 경로는 / 로 시작하는 상대 경로만(request_problem). 만든 주소의 scheme·host·port 가 연결 주소와 같은지 다시 맞춘다.
- 주소(base_url_problem): http(s) 만, localhost·내부망 IP 꼴 거절. 부를 때는 호스트를 RESOLVE 로 풀어 모든 IP 가
  공인일 때만 연결한다(시험은 RESOLVE 를 바꿔 끼운다).
- 키: 질의(key_in query)면 연결의 key_name 그대로(대소문자 유지), 기상청과 같은 규칙으로 인코딩 키(% 있음)는 그대로,
  디코딩 키는 한 번만 인코딩한다. 머리글(header)이면 `key_name: 키`. 경로 질의·params 에 같은 이름(대소문자 무시)이 오면 거절.
- 이 함수 밖으로 나가는 것(본문·오류·주소·로그)에서 키를 지운다(scrub — 그대로·인코딩·디코딩 꼴, key_name 질의 값).
  예외 글은 담지 않고 종류만 code 로 바꾼다. httpx 요청 기록 줄은 _HideKey 가 지운다.
- 공공데이터포털 게이트웨이 오류(OpenAPI_ServiceResponse/cmmMsgHeader, JSON·XML)는 기상청과 같은 표(kma)로 읽고,
  메시지의 「기상청」을 연결 이름으로 바꿔 쓴다. 응답 머리(resultCode)는 읽지 않는다 — 본문 그대로 에이전트가 읽는다.
- XML 은 표준 라이브러리로만 바꾼다. DTD(<!DOCTYPE·<!ENTITY)가 있으면 바꾸지 않고(엔터티를 풀지 않는다) 깊이·마디 수를 막는다.
"""

import asyncio
import ipaddress
import json
import logging
import re
import socket
import xml.etree.ElementTree as ET
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, quote_plus, unquote, urlencode

import httpx

from app.info import kma

logger = logging.getLogger(__name__)

TIMEOUT_S = 15.0
MAX_BYTES = 300 * 1024  # 본문은 여기까지만 읽는다
BODY_LIMIT = 3500  # 에이전트에게 주는 본문 글자 수
SAMPLE_LIMIT = 300  # 연결 시험·실패에 보이는 본문 앞부분
TRUNCATED_HINT = " …(뒤는 생략 — 범위를 좁혀 다시 부르세요)"
MAX_XML_DEPTH = 50
MAX_XML_NODES = 20_000
MASK = "[키 지움]"
KEY_NAME_PATTERN = r"^[A-Za-z0-9_.\-]{1,60}$"  # 질의 이름·머리글 이름으로 그대로 쓸 수 있는 꼴

# 시험이 가짜 transport 를 바꿔 끼운다.
TRANSPORT: httpx.AsyncBaseTransport | None = None

BAD_START = "path 는 / 로 시작하는 상대 경로만 됩니다(예: /getRestDeInfo)."
BAD_PART = "path 에 「{part}」는 쓸 수 없습니다 — 연결 주소 밖으로 나가는 경로는 부르지 않습니다."
KEY_PARAM = "키 이름({name})은 path·params 에 넣지 마세요 — 키는 코드가 붙입니다."
BAD_SCHEME = "주소는 http:// 또는 https:// 로 시작해야 합니다."
INTERNAL_HOST = "localhost 나 내부망(사설·루프백·링크로컬·멀티캐스트) 주소는 정보 API 주소로 쓸 수 없습니다."
RESOLVED_INTERNAL = "이 주소의 호스트가 내부망 IP 로 풀려 부르지 않았습니다."
OFF_BASE = "만든 주소가 연결 주소 밖이라 부르지 않았습니다."
REDIRECT = "{name} 응답이 다른 주소로 넘기는 응답(HTTP {status})이라 따라가지 않았습니다(리다이렉트는 따르지 않습니다). 주소·경로를 확인해 주세요."
_FORBIDDEN = ("://", "..", "@", "\\", "#")
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


async def _check_resolved(url: httpx.URL, name: str) -> None:
    """호스트를 풀어 모든 IP 가 공인일 때만 지나간다. IP 꼴은 base_url_problem 이 이미 봤다."""
    if _ip(url.host) is not None:
        return
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


# ── 키 ──────────────────────────────────────────────────────────────


def _forms(key: str) -> list[str]:
    """지울 키 꼴: 그대로·디코딩·인코딩(한 번)·JSON 의 \\/·+ 를 공백으로 읽은 꼴. 긴 것부터."""
    out: set[str] = set()
    for base in {key, unquote(key)}:
        out |= {base, quote(base, safe=""), quote_plus(base, safe=""), quote(base), base.replace("/", "\\/"),
                base.replace("+", " ")}
    return sorted((f for f in out if f), key=len, reverse=True)


def scrub(text: str, key: str, *, key_name: str | None = None) -> str:
    """text 에서 키(여러 꼴, 대소문자 무시)와 key_name 질의 값(대소문자 무시)을 지운다."""
    if key:
        text = re.sub("|".join(map(re.escape, _forms(key))), MASK, text, flags=re.IGNORECASE)
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
        parts.append(f"{conn.key_name}={kma._encoded(conn.key)}")
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
    return kma._REASONS.get(reason.zfill(2), "unknown")


def body_for_model(text: str, cut: bool) -> tuple[str, bool]:
    """(에이전트에게 줄 본문 ≤ BODY_LIMIT 자, 잘렸는가). 잘리면 끝에 TRUNCATED_HINT."""
    if len(text) <= BODY_LIMIT and not cut:
        return text, False
    return text[: BODY_LIMIT - len(TRUNCATED_HINT)] + TRUNCATED_HINT, True


def _status_code(status: int, data: object) -> str | None:
    """실패 code 또는 None(2xx 이고 게이트웨이 오류가 아님). 게이트웨이 오류를 상태보다 먼저 본다(403 + 봉투)."""
    if 300 <= status < 400:
        return "redirect"
    if (gate := gateway_code(data)) is not None:
        return gate
    if status >= 500:
        return "server_error"
    if status >= 400 or status < 200:
        return kma._STATUS.get(status, "unknown")
    return None


async def _read(response: httpx.Response) -> tuple[bytes, bool]:
    chunks, size = [], 0
    async for chunk in response.aiter_bytes():
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BYTES:
            return b"".join(chunks)[:MAX_BYTES], True
    return b"".join(chunks), False


# ── 부르기 ──────────────────────────────────────────────────────────


async def fetch(conn: GenericConn, path: str, params: dict[str, str]) -> Fetched:
    """연결 주소 + path 를 GET 으로 한 번 부른다. 2xx 이고 게이트웨이 오류가 아니면 Fetched, 아니면 GenericFailed."""
    problem = request_problem(path, params, conn.key_name)
    if problem is not None:
        raise GenericFailed("bad_path", problem)
    problem = base_url_problem(conn.base_url)
    if problem is not None:
        raise GenericFailed("blocked_host", problem)
    base = httpx.URL(conn.base_url)
    url = _url(conn, path, params, with_key=True)
    shown = scrub(str(_url(conn, path, params, with_key=False)), conn.key, key_name=conn.key_name)
    if not _on_base(url, base):
        raise GenericFailed("bad_path", OFF_BASE)
    await _check_resolved(base, conn.name)
    headers = {"Accept-Encoding": "identity"}
    if conn.key_in == "header":
        headers[conn.key_name] = conn.key
    code: str | None = None
    token = _CURRENT.set((conn.key_name, conn.key))
    try:
        async with (
            asyncio.timeout(TIMEOUT_S),
            httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_S, trust_env=False, follow_redirects=False) as http,
            http.stream("GET", url, headers=headers) as response,
        ):
            raw, cut = await _read(response)
            status = response.status_code
            content_type = response.headers.get("content-type", "")
            charset = response.charset_encoding
    except (httpx.TimeoutException, TimeoutError):
        code = "timeout"
    except httpx.HTTPError as exc:  # 예외 글에 주소(키)가 있을 수 있어 종류만 남긴다
        code = "bad_url" if isinstance(exc, httpx.ConnectError | httpx.UnsupportedProtocol) else "unknown"
    except Exception:  # noqa: BLE001 — 어떤 예외 글도 밖으로 내지 않는다(키가 있을 수 있다)
        code = "unknown"
    finally:
        _CURRENT.reset(token)
    if code is not None:
        logger.warning("정보 API 호출 실패: %s code=%s", conn.name, code)
        raise GenericFailed(code, failure_message(code, conn.name))
    text = _decode(raw, charset)
    data = _parse(text, content_type)
    text = scrub(text if data is None else json.dumps(data, ensure_ascii=False), conn.key, key_name=conn.key_name)
    code = _status_code(status, data)
    if code is not None:
        logger.warning("정보 API 호출 실패: %s code=%s status=%s", conn.name, code, status)
        message = REDIRECT.format(name=conn.name, status=status) if code == "redirect" else failure_message(
            code, conn.name)
        raise GenericFailed(code, message, http_status=status, sample=text[:SAMPLE_LIMIT])
    return Fetched(http_status=status, content_type=content_type, text=text, cut=cut, url=shown)
