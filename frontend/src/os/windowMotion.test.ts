import { afterEach, expect, test, vi } from 'vitest';
import {
  closeFrames,
  dockIconCenter,
  minimizeFrames,
  MOTION_MS,
  motionOn,
  openFrames,
  setDockAnchor,
  setWindowMotion,
  zoomFrames,
} from './windowMotion';

const reducedMotion = (on: boolean) =>
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: on && q.includes('reduce'), media: q, addEventListener() {}, removeEventListener() {} }));

/** getBoundingClientRect 이 (left, top, size×size) 를 돌려주는 Dock 타일 대역. */
const tile = (left: number, top: number, size = 48) => {
  const el = document.createElement('span');
  el.getBoundingClientRect = () =>
    ({ left, top, width: size, height: size, right: left + size, bottom: top + size, x: left, y: top, toJSON() {} }) as DOMRect;
  return el;
};

afterEach(() => {
  setWindowMotion(false);
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

test('motion is off under the test runner until a test turns it on', () => {
  expect(motionOn()).toBe(false);
  setWindowMotion(true);
  expect(motionOn()).toBe(true);
});

test('reduced motion turns motion off even when the switch is on', () => {
  setWindowMotion(true);
  reducedMotion(true);
  expect(motionOn()).toBe(false);
  reducedMotion(false);
  expect(motionOn()).toBe(true);
});

test('durations: open 220, close 160, minimize and restore 260, maximize 200 (ms)', () => {
  expect(MOTION_MS).toEqual({ open: 220, close: 160, minimize: 260, restore: 260, zoom: 200 });
});

test('open grows from 0.6 to full size and fades in, about the origin point in window coordinates', () => {
  const frames = openFrames({ x: 100, y: 80, w: 800, h: 600 }, { x: 960, y: 1027 });
  expect(frames[0]).toMatchObject({ transform: 'scale(0.6)', opacity: 0, transformOrigin: '860px 947px' });
  expect(frames.at(-1)).toMatchObject({ transform: 'scale(1)', opacity: 1, transformOrigin: '860px 947px' });
});

test('close shrinks a little and fades out where the window is', () => {
  expect(closeFrames()).toEqual([
    { transform: 'scale(1)', opacity: 1 },
    { transform: 'scale(0.92)', opacity: 0 },
  ]);
});

test('minimize ends as an icon-sized window centred on the Dock icon', () => {
  const frames = minimizeFrames({ x: 100, y: 100, w: 800, h: 600 }, { x: 960, y: 1027 });
  expect(frames[0]).toMatchObject({ transformOrigin: '0px 0px', transform: 'translate(0px, 0px) scale(1)', opacity: 1 });
  // 48 / 800 = 0.06 → 48×36 상자의 가운데가 (960, 1027): 960 − 100 − 24 = 836, 1027 − 100 − 18 = 909
  expect(frames.at(-1)).toMatchObject({ transformOrigin: '0px 0px', transform: 'translate(836px, 909px) scale(0.06)', opacity: 0 });
});

test('maximize starts at the old frame and ends at the new one (only transform, no layout)', () => {
  const frames = zoomFrames({ x: 100, y: 100, w: 960, h: 516 }, { x: 0, y: 48, w: 1920, h: 1032 });
  expect(frames[0]).toEqual({ transformOrigin: '0px 0px', transform: 'translate(100px, 52px) scale(0.5, 0.5)' });
  expect(frames.at(-1)).toEqual({ transformOrigin: '0px 0px', transform: 'translate(0px, 0px) scale(1, 1)' });
});

test('the Dock icon centre comes from the registered tile; a Dock hidden below the screen counts as shown', () => {
  vi.stubGlobal('innerHeight', 1080);
  const shown = document.body.appendChild(tile(900, 1003));
  setDockAnchor('schedule', shown);
  expect(dockIconCenter('schedule')).toEqual({ x: 924, y: 1027 });
  setDockAnchor('schedule', document.body.appendChild(tile(900, 1200))); // 확대한 창 때문에 Dock 이 아래로 숨어 있다
  expect(dockIconCenter('schedule')).toEqual({ x: 924, y: 1027 });
  expect(dockIconCenter('questionnaire')).toBeNull(); // Dock 에 없는 프로그램
});

test('a tile that left the Dock or was never laid out gives no icon centre', () => {
  const gone = document.body.appendChild(tile(900, 1003));
  setDockAnchor('schedule', gone);
  gone.remove(); // 임시 항목이 Dock 에서 빠졌다
  expect(dockIconCenter('schedule')).toBeNull();
  setDockAnchor('chat', document.body.appendChild(document.createElement('span'))); // 크기 0
  expect(dockIconCenter('chat')).toBeNull();
});
