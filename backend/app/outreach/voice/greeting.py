"""통화 첫마디(Task 87): 코드가 고정 틀로 짓는다 — AI 임과 기록됨을 늘 밝히고, 번호나 모델이 쓴 글이 들어갈 자리가 없다.

- 들어가는 것은 현장 이름과 사람 이름뿐이다. 이름 칸에 번호가 적혀 있으면 번호만 빼고, 줄 바꿈·제어 글자·보이지 않는 글자는
  빈칸으로 바꾼다(숫자 사이에 낀 것은 빼서 붙인다 — 번호를 쪼개 숨기지 못하게). 번호를 빼고 남는 것이 없으면 거는 통화는
  ValueError(받은 값은 싣지 않는다), 받는 통화는 현장 이름 없는 문장. 번호 찾기는 redact.hide_phones 이고 그 한계를 물려받는다
  (사람이 일부러 띄어 적은 드문 꼴) — 이름 칸에 번호를 적지 않는 것이 첫째 줄이다.
- 없는 언어는 한국어(DEFAULT_LANGUAGE — languages.code 와 같은 읽기). 언어마다(Task 100 — languages.SUPPORTED 넷) 다섯 표
  (FIRST_LINES·INBOUND_LINES·INBOUND_LINES_NO_SITE·DISCLOSURES·CORE·MUST_NOT_SAY·KEYWORDS·RETRACT)를 함께 채운다 — 한국어 문장의 뜻 그대로, AI 임과
  「이 통화는 기록됩니다」를 넣고, 틀에는 숫자를 쓰지 않는다. 표에 있어도 통화가 되는지는 languages.CALLABLE 이 정한다(통화 일꾼이
  languages.call_language 로 고른다 — 안 되는 언어는 한국어 문장으로 건다).
- discloses(language, spoken) — 음성 모델이 **실제로 한** 첫 발화(받아쓰기)가 우리 밝힘을 했는가. 세 겹을 함께 본다(고침 3):
  ① 문장 일치 — 받아쓰기와 DISCLOSURES 의 밝힘 문장(현장·사람 이름 자리를 뺀 것)을 NFKC·소문자·ALIASES(「크로노스」「에이 아이」)·
  글자와 숫자만으로 고르고, 문장 길이 ±WINDOW_SLACK 창 가운데 가장 비슷한 것의 difflib 비율 ≥ SIMILAR(0.75), 묶음마다.
  ② 핵심 낱말 — 그 맞은 자리(창 둘레에서 문장 글자가 맞은 처음~끝, 낱말 끝까지)에 CORE 가 글자 그대로(「ChronOS AI 비서입니다」 ·
  「(기록|녹음)(됩니다|돼요|되고 있습니다)」 · 「ChronOS AI assistant」 · 「is (being) recorded」) — 「사람 비서」「non-AI」「faux AI」
  「unrecorded」「기록됩니까」「비서였습니다」는 아니다. 그 자리와 바로 뒤 낱말 하나(문장부호는 건너고 쉼표는 건너지 않는다 —
  「recorded? No.」)에 MUST_NOT_SAY 가 없어야 한다. ③ 마디 거부 — 첫 발화 전체의 마디(문장부호·and/but/so/or) 가운데 KEYWORDS 가 든
  마디에 MUST_NOT_SAY 가 함께 있거나 RETRACT(「just kidding」)가 어디든 있으면 거부. 받아쓰기는 앞 MAX_HEARD 글자만 본다.
  SDK 에는 「이 문장을 그대로 말하라」가 없어 첫마디를 모델이 말하므로(지시문은 그대로 말하라고 한다), 통화 일꾼이 통화의 첫 발화
  (session 의 약속 2)를 이것으로 본다(call_run._discloses) — 아니면 고정 첫마디를 한 번 더 시키고 그래도 아니면 끊는다. 이 검사는
  고정 첫마디 지시와 함께 쓰는 한 겹이다(알려진 틈은 task-100-report 「고침 3」).
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
# 밝힘 문장: 고정 첫마디에서 현장·사람 이름 자리를 뺀 부분(AI 비서 문장, 기록 문장). 묶음마다 하나가 들려야 한다(묶음 안의 뒤의 것은
# 받아쓰기·말투 변형 — 「돼요」「되고 있습니다」. 「녹음 중입니다」는 넣지 않는다).
DISCLOSURES = {
    "ko": (("일정 담당 ChronOS AI 비서입니다",),
           ("이 통화는 기록됩니다", "이 통화는 녹음됩니다", "이 통화는 기록돼요", "이 통화는 녹음돼요", "이 통화는 기록되고 있습니다",
            "이 통화는 녹음되고 있습니다")),
    "en": (("this is the ChronOS AI assistant",), ("This call is recorded", "This call is being recorded")),
    "zh": (("我是负责",), ("日程的ChronOS AI助理",), ("本次通话将被录音",)),  # 현장 이름이 「我是负责」와 「日程的…」 사이에 든다
    "vi": (("tôi là trợ lý AI ChronOS phụ trách lịch trình",), ("Cuộc gọi này được ghi âm",)),
}
# 핵심 낱말(묶음마다, 맞은 자리 안에 글자 그대로 — 고침 3): 비율만으로는 「ChronOS 사람 비서」「non-AI」「faux AI」「unrecorded」가 지나간다.
# 한국어 끝은 다/요만(「입니까」「였습니다」는 아니다). 한국어·중국어는 빈칸을 뺀 자리에, 영어·베트남어는 빈칸 한 칸 자리에 건다.
CORE = {
    "ko": (re.compile(r"chronos(?:ai|인공지능)비서(?:입니다|이에요|예요)"),
           re.compile(r"(?:기록|녹음)이?(?:됩니다|돼요|되요|되고있습니다)")),
    "en": (re.compile(r"(?<![\w-])chronos\s?(?:ai|a\.\s?i\.?)\s+assistant(?![\w-])"),
           re.compile(r"(?<![\w-])(?:is|being)\s+recorded(?![\w-])")),
    "zh": (re.compile(r"我是负责"), re.compile(r"chronosai助理"), re.compile(r"(?<!不)被录音")),
    "vi": (re.compile(r"(?<!\w)trợ\s?l[ýí]\s?ai\s?chronos(?!\w)"), re.compile(r"(?<!\w)được\s?ghi\s?âm(?!\w)")),
}
# 받아쓰기가 소리대로·틀리게 적는 꼴 → 우리 낱말(빈칸이 끼어도 — 「에이 아이」). 고른 뒤, 빈칸을 빼기 전에 바꾼다.
ALIASES = ((re.compile(r"크로\s*[노너]\s*스"), "chronos"), (re.compile(r"에이\s*아이"), "ai"),
           (re.compile(r"(?<![a-z])(?:kronos|cronos|chronus)(?![a-z])"), "chronos"))
SIMILAR = 0.75  # 창과 문장의 difflib 비율(핵심 낱말·마디 거부와 함께 — 혼자 지키는 문이 아니다)
WINDOW_SLACK = 4  # 창 길이 = 문장 길이 ± 이만큼(글자)
MAX_HEARD = 600  # 보는 받아쓰기 글자(고른 뒤) — 첫 발화는 짧다
# 부정·끔 말: 맞은 자리 안, 그 자리 바로 뒤 낱말 하나(쉼표를 건너지 않고 · 「recorded? No.」), 그리고 밝힘 낱말(KEYWORDS)이 든 마디 어디든 있으면 밝힌 것이 아니다.
MUST_NOT_SAY = {
    "ko": ("않", "아니", "아닙", "아닌", "아님", "아뇨", "아냐", "못", "없", "꺼", "껐", "중단", "중지", "정지", "해제", "금지", "생략",
           "삭제", "제외", "미녹음", "비녹음", "무녹음", "미기록", "비기록"),
    "en": ("not", "n't", "n’t", "no", "never", "without", "cannot", "neither", "none", "off", "stop", "stopped", "disabled",
           "nothing", "zero", "nope", "false", "kidding"),
    "zh": ("不是", "不会", "不會", "没有", "沒有", "不录", "不錄", "不记录", "不記錄", "并非", "並非", "不被", "无", "無", "关闭", "停止",
           "取消", "删除", "关掉"),
    "vi": ("không phải", "không được ghi", "không ghi", "chẳng", "không bị", "không có", "tắt", "dừng", "ngừng", "xóa"),
}
KEYWORDS = {  # 마디 거부를 거는 밝힘 낱말
    "ko": ("기록", "녹음", "ai", "인공지능", "비서"),
    "en": ("ai", "a.i", "assistant", "record", "records", "recorded", "recording"),
    "zh": ("录音", "记录", "錄音", "記錄", "ai", "助理", "人工智能"),
    "vi": ("ghi âm", "ghi lại", "ai", "trợ lý"),
}
RETRACT = {"ko": ("농담", "장난"), "en": ("kidding", "joking", "nope"), "zh": ("开玩笑",), "vi": ("đùa",)}  # 어디에 있어도 거부
_CLAUSE = re.compile(r"[.!?;,。！？；，、\n]+|\s(?:and|but|so|or|và|nhưng)\s")
_COMMA = ",，、"
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


def _spoken(text: object) -> str:
    """NFKC·소문자·빈칸 한 칸·ALIASES 를 바꾼 글(부정·핵심 낱말은 이 글에서 찾는다)."""
    out = " ".join(unicodedata.normalize("NFKC", text).lower().split()) if isinstance(text, str) else ""
    for pattern, meant in ALIASES:
        out = pattern.sub(meant, out)
    return out


def _flat(text: str, code: str = DEFAULT_LANGUAGE) -> tuple[str, list[int]]:
    """(견줄 꼴 — _spoken 에서 글자와 숫자만, 그 글자마다 _spoken 글에서의 자리)."""
    spoken = _spoken(text)
    pairs = [(char, at) for at, char in enumerate(spoken) if char.isalnum()]
    return "".join(char for char, _ in pairs), [at for _, at in pairs]


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


def _plain(code: str, text: str) -> str:
    return text if code in _BY_WORD else "".join(text.split())


def _negated(code: str, text: str) -> bool:
    heard = _plain(code, text)
    return any(_has(code, heard, word) for word in MUST_NOT_SAY[code]) or (code == "ko" and bool(_KO_SPACED_NOT.search(text)))


def _next_word(code: str, spoken: str, at: int) -> str:
    """맞은 자리 바로 뒤 낱말(문장부호를 건너서 — 쉼표면 빈 글). 베트남어는 두 낱말(「không phải」), 중국어는 세 글자."""
    while at < len(spoken) and not spoken[at].isalnum():
        if spoken[at] in _COMMA:
            return ""
        at += 1
    if code == "zh":
        return spoken[at:at + 3]
    words = spoken[at:].split()
    return " ".join(words[:2] if code == "vi" else words[:1])


def _heard(code: str, spoken: str, flat: str, where: list[int], sentence: str, core: re.Pattern, scan: str) -> bool:
    target = _flat(sentence, code)[0]
    ratio, start, end = _best(flat, target)
    if ratio < SIMILAR or end <= start:
        return False
    # 볼 자리: 창 둘레(±문장 길이의 1/3)에서 문장 글자가 맞은 첫 글자부터 끝 글자까지 — 끼어든 말(「가 아닙」 · 「không phải」)까지 덮는다
    around = max(WINDOW_SLACK, len(target) // 3)
    base = max(0, start - around)
    blocks = [b for b in SequenceMatcher(None, flat[base:end + around], target, autojunk=False).get_matching_blocks() if b.size]
    start, end = base + blocks[0].a, base + blocks[-1].a + blocks[-1].size
    left, right = where[start], where[end - 1] + 1
    if code != "zh":  # 낱말 끝까지 늘린다(「기록돼요」·「isn't」) — 중국어는 낱말 사이에 빈칸이 없어 창 그대로
        while left > 0 and spoken[left - 1].isalnum():
            left -= 1
        while right < len(spoken) and (spoken[right].isalnum() or spoken[right] in "'’"):
            right += 1
    span = spoken[left:right]
    if not core.search(_plain(code, span)) or _negated(code, scan[left:right]):
        return False
    return not _negated(code, _next_word(code, scan, right))


def _vetoed(code: str, spoken: str) -> bool:
    """첫 발화 전체에서: 밝힘 낱말이 든 마디에 부정·끔 말이 함께 있거나, 되돌리는 말(「just kidding」)이 어디든 있으면 참(고침 3)."""
    if any(_has(code, _plain(code, spoken), word) for word in RETRACT[code]):
        return True
    for clause in _CLAUSE.split(spoken):
        heard = _plain(code, clause.strip())
        if any(_has(code, heard, word) for word in KEYWORDS[code]) and _negated(code, clause.strip()):
            return True
    return False


def _names(code: str, line: object) -> list[str]:
    """우리가 지은 첫마디(first_line·inbound_line)에서 그 틀에 넣은 현장·사람 이름을 되읽는다(틀과 맞지 않으면 빈 목록)."""
    if not isinstance(line, str):
        return []
    for table in (FIRST_LINES, INBOUND_LINES):
        pattern = re.escape(table[code]).replace(r"\{site\}", "(?P<site>.+?)").replace(r"\{name\}", "(?P<name>.+?)")
        found = re.fullmatch(pattern, line)
        if found:
            return [value for value in found.groupdict().values() if value]
    return []


def _neutral(code: str, text: str, names: list[str]) -> str:
    """부정을 찾는 사본: 이름(고른 꼴, 문장부호·빈칸이 달라도)을 같은 길이의 「q」로 — 자리는 그대로라 맞은 자리 계산은 같다."""
    for name in names:
        words = [word for word in re.split(r"[^\w]+", _spoken(name)) if word]
        if not words:
            continue
        # 낱말 경계로(라틴 글자·숫자에 붙지 않게 — 「No」가 「Nothing」을 가리지 않는다). 한글 조사(「님」)·한자 앞뒤에는 붙어도 된다
        pattern = re.compile(r"(?<![a-z0-9])" + r"[^\w]*".join(re.escape(word) for word in words) + r"(?![a-z0-9])")
        text = pattern.sub(lambda hit: "q" * len(hit.group()), text)
    return text


def discloses(language: str, spoken: str, first_line: str | None = None) -> bool:
    """실제로 한 말에 그 언어의 밝힘 문장(AI 비서 · 기록됨)이 모두 들렸는가(모듈 머리 글). 모르는 언어는 한국어 기준.
    first_line 은 그 통화에 시킨 우리 첫마디(spec.first_line) — 그 안의 현장·사람 이름은 부정·끔 말 찾기(마디 거부·자리 뒤 낱말)에서
    빼고 본다(「No.3 plant」「못골 현장」「无锡」이 모든 통화를 끊지 않게). 핵심 낱말·문장 일치는 그대로."""
    code = _language(language)
    text = _spoken(spoken)
    flat, where = _flat(text, code)
    flat, where = flat[:MAX_HEARD], where[:MAX_HEARD]
    text = text[:where[-1] + 1] if where else ""
    scan = _neutral(code, text, _names(code, first_line))
    if not flat or _vetoed(code, scan):
        return False
    return all(any(_heard(code, text, flat, where, sentence, core, scan) for sentence in group)
               for group, core in zip(DISCLOSURES[code], CORE[code], strict=True))
