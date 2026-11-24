"""통화 첫마디(Task 87): 코드가 고정 틀로 짓는다 — AI 임과 기록됨을 늘 밝히고, 번호나 모델이 쓴 글이 들어갈 자리가 없다.

- 들어가는 것은 현장 이름과 사람 이름뿐이다. 이름 칸에 번호가 적혀 있으면 번호만 빼고, 줄 바꿈·제어 글자·보이지 않는 글자는
  빈칸으로 바꾼다(숫자 사이에 낀 것은 빼서 붙인다 — 번호를 쪼개 숨기지 못하게). 번호를 빼고 남는 것이 없으면 거는 통화는
  ValueError(받은 값은 싣지 않는다), 받는 통화는 현장 이름 없는 문장. 번호 찾기는 redact.hide_phones 이고 그 한계를 물려받는다
  (사람이 일부러 띄어 적은 드문 꼴) — 이름 칸에 번호를 적지 않는 것이 첫째 줄이다.
- 없는 언어는 한국어(DEFAULT_LANGUAGE — languages.code 와 같은 읽기). 언어마다(Task 100 — languages.SUPPORTED 넷) 다섯 표
  (FIRST_LINES·INBOUND_LINES·INBOUND_LINES_NO_SITE·DISCLOSURES·MUST_NOT_SAY)를 함께 채운다 — 한국어 문장의 뜻 그대로, AI 임과
  「이 통화는 기록됩니다」를 넣고, 틀에는 숫자를 쓰지 않는다. 표에 있어도 통화가 되는지는 languages.CALLABLE 이 정한다(통화 일꾼이
  languages.call_language 로 고른다 — 안 되는 언어는 한국어 문장으로 건다).
- discloses(language, spoken) — 음성 모델이 **실제로 한** 말(받아쓰기)에 **우리 고정 첫마디의 밝힘 문장**(DISCLOSURES — 「일정 담당
  ChronOS AI 비서입니다」와 「이 통화는 기록됩니다」, 언어마다)이 들렸는가(고침 2 — 낱말이 아니라 문장으로). 받아쓰기와 문장을 같은
  꼴(NFKC·소문자·글자와 숫자만, ALIASES — 「크로노스」→chronos)로 고른 뒤, 문장 길이 ±WINDOW_SLACK 의 창 가운데 가장 비슷한 것의
  difflib 비율이 SIMILAR(0.85) 이상이고 **그 창(낱말 끝까지 늘린 것) 안에** 부정 말(MUST_NOT_SAY · 「안 하/안 됩/못 하」)이 없어야 한다 —
  창 밖의 부정(「not a human」 · 「no number is shared」)은 상관없다. 현장·사람 이름 자리는 견주는 문장에 들어 있지 않다. 받아쓰기는
  앞 MAX_HEARD 글자만 본다. SDK 에는 「이 문장을 그대로 말하라」가 없어 첫마디를 모델이 말하므로(지시문은 그대로 말하라고 한다),
  통화 일꾼이 통화의 첫 발화(session 의 약속 2)를 이것으로 본다(call_run._discloses) — 바꿔 말했으면 고정 첫마디를 한 번 더 시키고 끊는다.
"""

import re
import unicodedata
from difflib import SequenceMatcher

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
# 밝힘 문장: 고정 첫마디에서 현장·사람 이름 자리를 뺀 부분(AI 비서 문장, 기록 문장). 묶음마다 하나가 들려야 한다(묶음 안의 뒤의 것은 같은 뜻의 다른 꼴).
DISCLOSURES = {
    "ko": (("일정 담당 ChronOS AI 비서입니다",), ("이 통화는 기록됩니다", "이 통화는 녹음됩니다")),
    "en": (("this is the ChronOS AI assistant",), ("This call is recorded", "This call is being recorded")),
    "zh": (("我是负责",), ("日程的ChronOS AI助理",), ("本次通话将被录音",)),  # 현장 이름이 「我是负责」와 「日程的…」 사이에 든다
    "vi": (("tôi là trợ lý AI ChronOS phụ trách lịch trình",), ("Cuộc gọi này được ghi âm",)),
}
ALIASES = {"ko": (("크로노스", "chronos"), ("에이아이", "ai"))}  # 받아쓰기가 소리대로 적는 꼴
SIMILAR = 0.85  # 창과 문장의 difflib 비율
WINDOW_SLACK = 4  # 창 길이 = 문장 길이 ± 이만큼(글자)
MAX_HEARD = 600  # 보는 받아쓰기 글자(고른 뒤) — 첫 발화는 짧다
# 밝힘 문장의 창 안에 있으면 그 문장은 밝힌 것이 아니다(「This call is not recorded」 · 「기록되지 않습니다」 · 不被录音 · không được ghi âm).
MUST_NOT_SAY = {
    "ko": ("아니", "아닙", "아닌", "아님", "아냐", "않", "없"),
    "en": ("not", "never", "n't", "n’t", "no", "cannot", "without", "neither"),
    "zh": ("不是", "不会", "不會", "没有", "沒有", "不录", "不錄", "不记录", "不記錄", "并非", "並非", "不被", "无", "無"),
    "vi": ("không phải", "không được ghi", "không ghi", "chẳng", "không bị", "không có"),
}
_KO_SPACED_NOT = re.compile(r"(?<![가-힣])(?:안|못)\s*(?:하|함|합|했|할|해|됩|돼|되|됨|된|될)")
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


def _flat(text: str, code: str) -> tuple[str, list[int]]:
    """(견줄 꼴 — NFKC·소문자·별칭·글자와 숫자만, 그 글자마다 고른 글(_spoken)에서의 자리)."""
    spoken = _spoken(text, code)
    flat, where = [], []
    for at, char in enumerate(spoken):
        if char.isalnum():
            flat.append(char)
            where.append(at)
    return "".join(flat), where


def _spoken(text: str, code: str) -> str:
    """NFKC·소문자·빈칸 한 칸·별칭을 바꾼 글(부정 말은 이 글에서 찾는다)."""
    out = " ".join(unicodedata.normalize("NFKC", text).lower().split()) if isinstance(text, str) else ""
    for heard, meant in ALIASES.get(code, ()):
        out = out.replace(heard, meant)
    return out


def _best(flat: str, target: str) -> tuple[float, int, int]:
    """flat 안에서 target 과 가장 비슷한 창 (비율, 시작, 끝). 같은 비율이면 긴 창(끼어든 말까지 덮게)."""
    best = (0.0, 0, 0)
    size = len(target)
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(target)
    for start in range(len(flat)):
        for length in range(max(1, size - WINDOW_SLACK), size + WINDOW_SLACK + 1):
            if start + length > len(flat):
                break
            matcher.set_seq1(flat[start:start + length])
            if matcher.real_quick_ratio() < best[0] or matcher.quick_ratio() < best[0]:
                continue
            ratio = matcher.ratio()
            if ratio > best[0] or (ratio == best[0] and length > best[2] - best[1]):
                best = (ratio, start, start + length)
    return best


def _negated(code: str, span: str) -> bool:
    heard = span if code in _BY_WORD else "".join(span.split())
    return any(_has(code, heard, word) for word in MUST_NOT_SAY[code]) or (code == "ko" and bool(_KO_SPACED_NOT.search(span)))


def _heard(code: str, spoken: str, flat: str, where: list[int], sentence: str) -> bool:
    target = _flat(sentence, code)[0]
    ratio, start, end = _best(flat, target)
    if ratio < SIMILAR or end <= start:
        return False
    # 부정을 볼 자리: 창 둘레(±문장 길이의 1/3)에서 문장 글자가 맞은 첫 글자부터 끝 글자까지 — 가장 비슷한 창이 문장 가운데·끝에 끼어든
    # 말(「비서가 아닙니다」의 「가 아닙」 · 「tôi không phải là」)을 빼고 잡혀도 그 말까지 덮는다. 문장이 끝난 뒤의 말은 덮지 않는다.
    around = max(WINDOW_SLACK, len(target) // 3)  # 끼어든 말이 창 밖으로 밀어낸 문장 글자(「tôi」)까지 닿게
    base = max(0, start - around)
    blocks = [b for b in SequenceMatcher(None, flat[base:end + around], target, autojunk=False).get_matching_blocks() if b.size]
    start, end = base + blocks[0].a, base + blocks[-1].a + blocks[-1].size
    left, right = where[start], where[end - 1] + 1
    if code != "zh":  # 낱말 끝까지 늘린다(「기록되지 않」의 「않」·「isn't」) — 중국어는 낱말 사이에 빈칸이 없어 창 그대로
        while left > 0 and spoken[left - 1].isalnum():
            left -= 1
        while right < len(spoken) and (spoken[right].isalnum() or spoken[right] in "'’"):
            right += 1
    return not _negated(code, spoken[left:right])


def discloses(language: str, spoken: str) -> bool:
    """실제로 한 말에 그 언어의 밝힘 문장(AI 비서 · 기록됨)이 모두 들렸는가(모듈 머리 글). 모르는 언어는 한국어 기준."""
    code = _language(language)
    text = _spoken(spoken, code) if isinstance(spoken, str) else ""
    flat, where = _flat(text, code)
    flat, where = flat[:MAX_HEARD], where[:MAX_HEARD]
    # _flat 은 이미 고른 글을 다시 고르지만 같은 글이 나온다(자리도 같다)
    return all(any(_heard(code, text, flat, where, sentence) for sentence in group) for group in DISCLOSURES[code])
