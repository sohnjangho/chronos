"""도구 이름을 LLM 쪽 이름으로 바꾼다.

OpenAI 함수 이름은 [a-zA-Z0-9_-] 만 되므로 점(.)을 밑줄 둘(__)로 바꾼다.
등록부가 이름에 __ 를 받지 않으므로 거꾸로 바꿔도 원래 이름이 나온다.
"""


def to_llm_name(name: str) -> str:
    return name.replace(".", "__")


def from_llm_name(name: str) -> str:
    return name.replace("__", ".")
