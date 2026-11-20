"""내장 위치 표: 이름 → ASOS 지점 번호·단기예보 격자(nx, ny). 시·도청 소재지와 큰 도시 30곳.

- 격자는 기상청 동네예보 격자(5km) 표의 시청 소재 동 값이다(격자 변환식으로 도심 좌표를 바꿔 이웃 칸 ±1 안임을
  확인했다, 11-20). ASOS 지점은 그 도시의 종관 관측소. 날씨 도구(info.weather)는 이 표에 있는 이름만 받는다.
- 이름은 「서울특별시」·「부산광역시」·「청주시」처럼 행정 꼬리말이 붙어도 찾는다. 도 이름은 도청 소재지로 본다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Place:
    name: str
    stn: str  # ASOS 지점 번호
    nx: int
    ny: int


PLACES: tuple[Place, ...] = (
    Place("서울", "108", 60, 127), Place("인천", "112", 55, 124), Place("수원", "119", 60, 121),
    Place("파주", "99", 56, 131), Place("이천", "203", 68, 121), Place("춘천", "101", 73, 134),
    Place("원주", "114", 76, 122), Place("강릉", "105", 92, 131), Place("속초", "90", 87, 141),
    Place("청주", "131", 69, 106), Place("충주", "127", 76, 114), Place("대전", "133", 67, 100),
    Place("세종", "239", 66, 103), Place("천안", "232", 63, 110), Place("홍성", "177", 55, 106),
    Place("전주", "146", 63, 89), Place("군산", "140", 56, 92), Place("광주", "156", 58, 74),
    Place("목포", "165", 50, 67), Place("여수", "168", 73, 66), Place("대구", "143", 89, 90),
    Place("안동", "136", 91, 106), Place("포항", "138", 102, 94), Place("구미", "279", 84, 96),
    Place("울산", "152", 102, 84), Place("부산", "159", 98, 76), Place("창원", "155", 90, 77),
    Place("진주", "192", 81, 75), Place("제주", "184", 52, 38), Place("서귀포", "189", 52, 33),
)
# 도 이름 → 도청 소재지(가장 가까운 관측소)
ALIASES = {"경기": "수원", "강원": "춘천", "충북": "청주", "충청북": "청주", "충남": "홍성", "충청남": "홍성",
           "전북": "전주", "전라북": "전주", "전남": "목포", "전라남": "목포", "경북": "안동", "경상북": "안동",
           "경남": "창원", "경상남": "창원"}
_SUFFIXES = ("특별자치시", "특별자치도", "특별시", "광역시", "시", "군", "도")
_BY_NAME = {p.name: p for p in PLACES}
# 둘 이상으로 읽히는 이름 → 되물을 말. 「광주」·「광주광역시」는 광역시로 본다.
AMBIGUOUS = {"광주시": "광주광역시인지 경기 광주시인지 알려 주세요"}


def ambiguous(name: str) -> str | None:
    """되물어야 하는 이름이면 그 말, 아니면 None."""
    return AMBIGUOUS.get("".join(name.split()))


def find(name: str) -> Place | None:
    """이름(꼬리말·띄어쓰기 무시)으로 찾는다. 없으면 None."""
    key = "".join(name.split())
    for candidate in (key, *(key[: -len(s)] for s in _SUFFIXES if key.endswith(s) and len(key) > len(s))):
        if candidate in _BY_NAME:
            return _BY_NAME[candidate]
        if candidate in ALIASES:
            return _BY_NAME[ALIASES[candidate]]
    return None
