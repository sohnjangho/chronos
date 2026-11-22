"""파일 이름·앞 바이트로 받을 종류를 고른다. 받지 않으면 None, 그때 화면에 보일 안내는 refusal()."""

from pathlib import PurePath

KINDS: dict[str, str] = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".csv": "table", ".tsv": "table",
    ".xlsx": "sheet",
    ".pdf": "pdf",
    ".docx": "doc", ".pptx": "doc", ".hwpx": "doc",
    ".txt": "text", ".md": "text",
}
MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".csv": "text/csv", ".tsv": "text/tab-separated-values",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".hwpx": "application/hwp+zip",
    ".txt": "text/plain", ".md": "text/markdown",
}
ACCEPTED = "그림(png·jpg·webp)·csv·tsv·xlsx·pdf·docx·pptx·hwpx·txt·md"

# 받지 않는 확장자마다 바꿔 올리는 방법(설계 5-1 「안 받음」)
_REFUSALS: dict[str, str] = {
    ".hwp": "한글(hwp) 파일은 받지 않습니다. PDF 로 저장해 주세요",
    ".dwg": "도면(dwg) 파일은 받지 않습니다. PDF 로 저장해 주세요",
    ".mpp": "MS Project(mpp) 파일은 받지 않습니다. PDF 나 xlsx 로 저장해 주세요",
    ".xls": "옛 엑셀(xls) 파일은 받지 않습니다. xlsx 로 저장해 주세요",
    ".doc": "옛 워드(doc) 파일은 받지 않습니다. docx 나 PDF 로 저장해 주세요",
    ".ppt": "옛 파워포인트(ppt) 파일은 받지 않습니다. pptx 나 PDF 로 저장해 주세요",
    ".zip": "압축 파일은 받지 않습니다. 압축을 풀어 하나씩 올려 주세요",
}
_EXECUTABLE_HEADS = (b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"#!")


def ext_of(name: str) -> str:
    """소문자 확장자(점 포함). 없으면 빈 글."""
    return PurePath(name).suffix.lower()


_TEXT_KINDS = ("text", "table")  # 글 파일은 앞 바이트로 막지 않는다(「MZ세대」·「#!」 로 시작하는 글도 있다)


def kind_of(name: str, head: bytes) -> str | None:
    """image|table|sheet|pdf|doc|text. 받지 않는 확장자나, 글이 아닌 종류인데 실행 파일 머리면 None."""
    kind = KINDS.get(ext_of(name))
    if kind not in _TEXT_KINDS and head.startswith(_EXECUTABLE_HEADS):
        return None
    return kind


def refusal(name: str) -> str:
    """받지 않는 파일의 안내 글."""
    return _REFUSALS.get(ext_of(name), f"받지 않는 형식입니다. 받는 형식: {ACCEPTED}")
