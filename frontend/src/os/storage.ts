// 브라우저 저장소 읽기·쓰기. 저장소가 막혀 있어도(사생활 보호 창 등) 던지지 않는다 —
// 그때는 부르는 쪽 상태가 메모리에만 남는다.

export function loadJson(key: string): unknown {
  try {
    const text = localStorage.getItem(key);
    return text === null ? null : JSON.parse(text);
  } catch {
    return null;
  }
}

/** value 가 null 이면 지운다. */
export function saveJson(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // 저장소를 쓸 수 없으면 메모리에만 둔다.
  }
}
