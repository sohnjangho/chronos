"""뽑은 글을 검색용 조각으로 나눈다. 부분(쪽·시트 묶음·본문)마다 따로 나누고, 조각은 그 부분의 위치를 단다.

긴 부분은 size 자 창으로 자르고 다음 조각은 overlap 자 앞에서 시작한다(겹침은 언제나 정확히 overlap 자).
창의 뒤쪽 절반에 줄바꿈이 있으면 그 줄 끝에서 자른다. 조각 글은 원문 그대로(앞뒤 공백도) 둔다.
"""

from dataclasses import dataclass

SIZE = 800
OVERLAP = 100


@dataclass(frozen=True)
class Chunk:
    seq: int  # 파일 안 차례(0부터)
    locator: str
    text: str


def _cut(text: str, start: int, size: int) -> int:
    end = min(start + size, len(text))
    if end == len(text):
        return end
    newline = text.rfind("\n", start + size // 2, end)
    return newline + 1 if newline >= 0 else end


def _split(text: str, size: int, overlap: int) -> list[str]:
    pieces, start = [], 0
    while True:
        end = _cut(text, start, size)
        pieces.append(text[start:end])
        if end == len(text):
            return pieces
        start = end - overlap


def chunks(parts: list[tuple[str, str]], size: int = SIZE, overlap: int = OVERLAP) -> list[Chunk]:
    """[(위치, 글)] → [Chunk]. 빈 부분(공백만)은 건너뛴다. overlap 은 size 의 절반보다 작아야 한다."""
    if not 0 <= overlap < size // 2:
        raise ValueError("overlap 은 size 의 절반보다 작아야 합니다")
    out: list[Chunk] = []
    for locator, text in parts:
        if not text.strip():
            continue
        base = len(out)
        out.extend(Chunk(base + i, locator, piece) for i, piece in enumerate(_split(text, size, overlap)))
    return out
