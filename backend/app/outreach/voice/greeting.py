"""통화 첫마디(Task 87): 코드가 고정 틀로 짓는다 — AI 임과 기록됨을 늘 밝히고, 번호나 모델이 쓴 글이 들어갈 자리가 없다.

- 들어가는 것은 현장 이름과 사람 이름뿐이다. 이름 칸에 번호가 적혀 있으면 번호만 빼고, 줄 바꿈·제어 글자·보이지 않는 글자는
  빈칸으로 바꾼다(숫자 사이에 낀 것은 빼서 붙인다 — 번호를 쪼개 숨기지 못하게). 번호를 빼고 남는 것이 없으면 거는 통화는
  ValueError(받은 값은 싣지 않는다), 받는 통화는 현장 이름 없는 문장. 번호 찾기는 redact.hide_phones 이고 그 한계를 물려받는다
  (사람이 일부러 띄어 적은 드문 꼴) — 이름 칸에 번호를 적지 않는 것이 첫째 줄이다.
- 없는 언어는 한국어(DEFAULT_LANGUAGE — languages.code 와 같은 읽기). 언어마다(Task 100 — languages.SUPPORTED 넷) 다섯 표
  (FIRST_LINES·INBOUND_LINES·INBOUND_LINES_NO_SITE·MUST_SAY·MUST_NOT_SAY)를 함께 채운다 — 한국어 문장의 뜻 그대로, AI 임과
  「이 통화는 기록됩니다」를 넣고, 틀에는 숫자를 쓰지 않는다. 표에 있어도 통화가 되는지는 languages.CALLABLE 이 정한다(통화 일꾼이
  languages.call_language 로 고른다 — 안 되는 언어는 한국어 문장으로 건다).
- discloses(language, spoken) — 음성 모델이 **실제로 한** 말(받아쓰기)이 AI 임(AI 낱말이 있고 NOT_AI — AI 를 바로 꾸미는 부정 — 가
  없음)과 기록됨(기록 낱말이 든 마디 가운데 같은 마디에 MUST_NOT_SAY 부정 말이 없는 것 하나)을 밝히는가(고침 1 — 부정은 그 마디 안에서만). SDK 에는 「이 문장을 그대로
  말하라」가 없어 첫마디를 모델이 말하므로, 통화 일꾼이 통화의 첫 발화(session 의 약속 2)를 이것으로 본다(call_run._discloses).
  한국어·중국어는 빈칸을 빼고 글자 조각으로, 영어·베트남어는 **낱말로** 본다(「wait」 속의 ai 는 AI 가 아니고, 「Nottingham」 속의
  not 은 부정이 아니다).
"""

import re
import unicodedata

from app.outreach import redact

DEFAULT_LANGUAGE = "ko"  # languages.DEFAULT 와 같다(이 모듈은 하네스 낱말·번호 가리기만 import 한다 — 표의 언어는 languages.SUPPORTED 넷)
FIRST_LINES = {
    "ko": "안녕하세요, {site} 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. {name}님 맞으신가요?",
    "en": "Hello, this is the ChronOS AI assistant in charge of the schedule for {site}. This call is recorded. "
          "Am I speaking with {name}?",
    "zh": "您好，我是负责{site}日程的ChronOS AI助理。本次通话将被录音。请问是{name}吗？",
    "vi": "Xin chào, tôi là trợ lý AI ChronOS phụ trách lịch trình của {site}. Cuộc gọi này được ghi âm. "
          "Xin hỏi có phải {name} ạ?",
}
INBOUND_LINES = {
    "ko": "안녕하세요, {site} 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?",
    "en": "Hello, this is the ChronOS AI assistant in charge of the schedule for {site}. This call is recorded. "
          "How can I help you?",
    "zh": "您好，我是负责{site}日程的ChronOS AI助理。本次通话将被录音。请问有什么可以帮您？",
    "vi": "Xin chào, tôi là trợ lý AI ChronOS phụ trách lịch trình của {site}. Cuộc gọi này được ghi âm. "
          "Tôi có thể giúp gì cho bạn?",
}
INBOUND_LINES_NO_SITE = {
    "ko": "안녕하세요, 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?",
    "en": "Hello, this is the ChronOS AI assistant in charge of schedules. This call is recorded. How can I help you?",
    "zh": "您好，我是负责日程的ChronOS AI助理。本次通话将被录音。请问有什么可以帮您？",
    "vi": "Xin chào, tôi là trợ lý AI ChronOS phụ trách lịch trình. Cuộc gọi này được ghi âm. Tôi có thể giúp gì cho bạn?",
}
# 꼭 하는 말: 묶음마다 하나는 들어 있어야 한다(소문자로 견준다 — 받아쓰기는 띄어쓰기·표기가 흔들린다).
MUST_SAY = {
    "ko": (("ai", "에이아이", "인공지능"), ("기록", "녹음")),
    "en": (("ai", "a.i", "a. i", "artificial intelligence"), ("recorded", "recording")),
    "zh": (("ai", "人工智能"), ("录音", "记录", "錄音", "記錄")),
    "vi": (("ai", "trí tuệ nhân tạo"), ("ghi âm", "ghi lại")),
}
# 기록 마디의 부정 말: 기록 낱말(MUST_SAY 의 둘째 묶음)과 **같은 마디**에 있으면 그 마디는 「기록됨」을 밝힌 것이 아니다
# (「이 통화는 기록되지 않습니다」 · No recording is made · 不被录音 · không bị ghi âm). 다른 마디의 부정(「사람이 아니라 AI 비서입니다」 ·
# 「not a human」)은 상관없다(고침 1). 한국어는 띄어 쓴 「안 하」「안 됩」「못 하」도 본다(_KO_SPACED_NOT — 「안녕하세요」는 아니다).
MUST_NOT_SAY = {
    "ko": ("아니", "아닙", "아닌", "아님", "않", "없"),
    "en": ("not", "never", "n't", "n’t", "no", "cannot", "without", "neither"),
    "zh": ("不是", "不会", "不會", "没有", "沒有", "不录", "不錄", "不记录", "不記錄", "并非", "並非", "不被", "无", "無"),
    "vi": ("không phải", "không được ghi", "không ghi", "chẳng", "không bị", "không có"),
}
_KO_SPACED_NOT = re.compile(r"(?<![가-힣])(?:안|못)\s*(?:하|함|합|했|할|해|됩|돼|되|됨|된|될)")
_AI_EN = r"(?:ai|a\.\s?i|artificial intelligence)(?!\w)"
# AI 를 **바로 꾸미는** 부정(「not an AI」 · 「AI 가 아닙니다」 · 「AI 아님」 · 不是AI · không phải là trợ lý AI) — 있으면 AI 임을 밝힌 것이 아니다.
# 한국어·중국어는 빈칸을 뺀 글에, 영어·베트남어는 빈칸 한 칸으로 고른 글에 건다.
NOT_AI = {
    "ko": re.compile(r"(?:ai|에이아이|인공지능)(?:비서|어시스턴트)?(?:가|이|는|은|도)?(?:아니|아닙|아님|아닌)"),
    "en": re.compile(rf"(?:(?<!\w)(?:not|never|no|neither)\s+|n['’]t\s+)(?:(?:a|an|the|real|actual)\s+)*{_AI_EN}"),
    "zh": re.compile(r"(?:不是|并非|並非)(?:一个|一個|一位)?(?:ai|人工智能)"),
    "vi": re.compile(r"(?<!\w)(?:không phải|chẳng phải)\s+(?:là\s+)?(?:một\s+)?(?:trợ lý\s+)?(?:ai|trí tuệ nhân tạo)(?!\w)"),
}
_CLAUSE = re.compile(r"[.!?;,。！？；，、\n]+")  # 마디 나누기(「A.I.」의 점도 나누지만 AI 낱말은 글 전체에서 찾는다)
_CONTRACTIONS = ("n't", "n’t")
_BY_WORD = frozenset({"en", "vi"})  # 빈칸으로 낱말을 가르는 언어 — 낱말(조각이 아니라)로 견준다
_SPACE_LIKE = frozenset({"Cc", "Cf", "Zl", "Zp"})  # 제어·보이지 않는 글자·줄 나눔
_HIDDEN = "\x00"  # 제어·보이지 않는 글자를 잠깐 바꿔 두는 표
_BETWEEN_DIGITS = re.compile(rf"(?<=[0-9０-９]){_HIDDEN}+(?=[0-9０-９])")
_EMPTY_BRACKETS = re.compile(r"[(（\[]\s*[)）\]]")  # 번호를 빼고 남은 빈 괄호


def _language(language: object) -> str:
    """languages.code 와 같은 읽기: 「EN」「en-US」「 vi 」 → 앞의 코드, 표에 없으면 한국어."""
    code = language.strip().lower().replace("_", "-").split("-")[0] if isinstance(language, str) else ""
    return code if code in FIRST_LINES else DEFAULT_LANGUAGE


def _clean(name: object) -> str:
    """이름 칸에서 번호·제어 글자를 뺀 글(없으면 빈 글)."""
    if not isinstance(name, str):
        return ""
    text = "".join(_HIDDEN if unicodedata.category(char) in _SPACE_LIKE else char for char in name)
    text = _BETWEEN_DIGITS.sub("", text).replace(_HIDDEN, " ")  # 숫자 사이에 낀 것은 붙인다(쪼갠 번호가 다시 이어지게)
    text = redact.hide_phones(text).replace(redact.PHONE_MASK, " ")
    return " ".join(_EMPTY_BRACKETS.sub(" ", text).split())


def first_line(language: str, site: str, name: str) -> str:
    """거는 통화의 첫마디. 현장 이름이나 사람 이름이 비었으면(번호뿐이어도) ValueError."""
    site_name, person = _clean(site), _clean(name)
    if not site_name or not person:
        raise ValueError("첫마디에 넣을 현장 이름과 사람 이름이 있어야 합니다")
    return FIRST_LINES[_language(language)].format(site=site_name, name=person)


def inbound_line(language: str, site: str | None) -> str:
    """받는 통화의 첫마디. 현장이 정해지지 않았으면 현장 이름 없이."""
    code, site_name = _language(language), _clean(site)
    return INBOUND_LINES[code].format(site=site_name) if site_name else INBOUND_LINES_NO_SITE[code]


def _word(word: str) -> re.Pattern:
    """낱말 하나(앞뒤에 다른 글자가 붙지 않은 것). 줄인 꼴 「n't」는 앞 낱말에 붙어 있으므로 뒤만 본다."""
    body = r"\s+".join(re.escape(part) for part in word.split())
    return re.compile(("" if word in _CONTRACTIONS else r"(?<!\w)") + body + r"(?!\w)")


def _has(code: str, heard: str, word: str) -> bool:
    return bool(_word(word).search(heard)) if code in _BY_WORD else "".join(word.split()) in heard


def _recorded(code: str, clause: str) -> bool:
    """이 마디가 기록됨을 밝히는가: 기록 낱말이 있고 같은 마디에 부정 말이 없다."""
    heard = clause.strip() if code in _BY_WORD else "".join(clause.split())
    if not any(_has(code, heard, word) for word in MUST_SAY[code][1]):
        return False
    if any(_has(code, heard, word) for word in MUST_NOT_SAY[code]):
        return False
    return not (code == "ko" and _KO_SPACED_NOT.search(clause))


def discloses(language: str, spoken: str) -> bool:
    """실제로 한 말이 그 언어로 AI 임(글 전체에 AI 낱말 · AI 를 바로 꾸미는 부정 없음)과 기록됨(부정 없는 마디 하나)을 밝히는가.
    모르는 언어는 한국어 기준."""
    code = _language(language)
    text = unicodedata.normalize("NFKC", spoken).lower() if isinstance(spoken, str) else ""
    spaced = " ".join(text.split())
    whole = spaced if code in _BY_WORD else "".join(text.split())
    if not any(_has(code, whole, word) for word in MUST_SAY[code][0]) or NOT_AI[code].search(whole):
        return False
    return any(_recorded(code, clause) for clause in _CLAUSE.split(spaced))
