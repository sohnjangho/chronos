// 사용자별 화면 설정(테마·Dock·배율)을 브라우저 저장소에 둔다. 저장소가 막혀도 던지지 않는다(storage.ts).
import { loadJson, saveJson } from './storage';

const key = (name: string, userId: number) => `chronos.${name}.${userId}`;

export function loadPref(name: string, userId: number | null): unknown {
  return userId === null ? null : loadJson(key(name, userId));
}

export function savePref(name: string, userId: number | null, value: unknown): void {
  if (userId !== null) saveJson(key(name, userId), value);
}
