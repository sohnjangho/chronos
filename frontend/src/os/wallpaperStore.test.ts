// 고른 배경·배치 방식은 계정마다 기억하고(이 브라우저 + 서버 ui-state 의 appearance), 기기 사이를 따라간다.
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { json, stubFetch } from '../test-helpers';
import { useWallpaper } from './wallpaperStore';

const KEY = (id: number) => `chronos.wallpaper.${id}`;
const stored = (id: number) => JSON.parse(localStorage.getItem(KEY(id)) ?? 'null');
const w = () => useWallpaper.getState();
let puts: string[];

beforeEach(() => {
  localStorage.clear();
  puts = [];
  w().reset();
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:photo-1'), revokeObjectURL: vi.fn() }));
});
afterEach(() => vi.unstubAllGlobals());

function server(appearance: unknown) {
  return stubFetch({
    '/api/me/ui-state': () => json(200, appearance ? { appearance } : {}),
    'PUT /api/me/ui-state/appearance': (init?: RequestInit) => {
      puts.push(String(init?.body));
      return json(200, { mode: 'appearance', updated_at: new Date().toISOString() });
    },
  });
}

test('처음은 기본 그라데이션·채우기', () => {
  w().load(1);
  expect(w().wallpaper).toBe('default');
  expect(w().fit).toBe('fill');
});

test('고르면 이 브라우저와 서버에 같이 쓰고, 다시 읽으면 그대로', async () => {
  server(null);
  w().load(1);
  w().choose('orbits');
  w().setFit('tile');
  await vi.waitFor(() => expect(puts.length).toBe(2));
  expect(JSON.parse(puts[1])).toEqual({ v: 1, wallpaper: 'orbits', fit: 'tile' });
  await vi.waitFor(() => expect(stored(1).dirty).toBe(false));
  expect(stored(1).state).toEqual({ v: 1, wallpaper: 'orbits', fit: 'tile' });
  w().reset();
  w().load(1);
  expect([w().wallpaper, w().fit]).toEqual(['orbits', 'tile']);
});

test('사람마다 따로', () => {
  w().load(1);
  w().choose('contours');
  w().load(2);
  expect(w().wallpaper).toBe('default');
  w().load(1);
  expect(w().wallpaper).toBe('contours');
});

test('다른 기기에서 고른 것(서버)을 받아 온다', async () => {
  server({ state: { v: 1, wallpaper: 'chronos-sky', fit: 'center' }, updated_at: new Date().toISOString() });
  w().load(1);
  await w().sync();
  expect([w().wallpaper, w().fit]).toEqual(['chronos-sky', 'center']);
  expect(puts).toEqual([]);
});

test('서버에 못 보낸 고름이 있으면 서버 것으로 덮지 않고 다시 보낸다', async () => {
  localStorage.setItem(KEY(1), JSON.stringify({ state: { v: 1, wallpaper: 'sculpt-mono', fit: 'fill' }, at: 0, dirty: true }));
  server({ state: { v: 1, wallpaper: 'orbits', fit: 'fill' }, updated_at: new Date().toISOString() });
  w().load(1);
  await w().sync();
  expect(w().wallpaper).toBe('sculpt-mono');
  expect(JSON.parse(puts[0]).wallpaper).toBe('sculpt-mono');
});

test('틀린 값은 기본으로', () => {
  localStorage.setItem(KEY(1), JSON.stringify({ state: { v: 1, wallpaper: '../evil', fit: 'zoom' }, at: 0, dirty: false }));
  w().load(1);
  expect([w().wallpaper, w().fit]).toEqual(['default', 'fill']);
});

test('사진을 올리면 내 사진으로 바뀌고, 지우면 기본으로', async () => {
  const sent: unknown[] = [];
  stubFetch({
    'PUT /api/me/wallpaper': (init?: RequestInit) => {
      sent.push(init?.body);
      return json(200, { type: 'image/png', width: 4, height: 3, bytes: 10, updated_at: new Date().toISOString() });
    },
    '/api/me/wallpaper': () => new Response(new Blob([new Uint8Array([1, 2])], { type: 'image/png' }), { status: 200 }),
    'DELETE /api/me/wallpaper': () => new Response(null, { status: 204 }),
    'PUT /api/me/ui-state/appearance': () => json(200, { mode: 'appearance', updated_at: new Date().toISOString() }),
  });
  w().load(1);
  const file = new File([new Uint8Array([1, 2])], 'IMG_0001.png', { type: 'image/png' });
  await w().uploadPhoto(file);
  expect(sent[0]).toBe(file);
  expect(w().wallpaper).toBe('photo');
  expect(w().photo).toEqual({ status: 'ready', url: 'blob:photo-1' });
  await w().removePhoto();
  expect(w().wallpaper).toBe('default');
  expect(w().photo.status).toBe('none');
});

test('너무 큰 사진·다른 형식은 보내기 전에 한국어로 막는다', async () => {
  const fetchFn = stubFetch({});
  w().load(1);
  const big = new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'a.jpg', { type: 'image/jpeg' });
  await expect(w().uploadPhoto(big)).rejects.toThrow('사진이 너무 큽니다. 10MB 까지 올릴 수 있습니다.');
  const gif = new File([new Uint8Array([1])], 'a.gif', { type: 'image/gif' });
  await expect(w().uploadPhoto(gif)).rejects.toThrow('JPG·PNG·WebP 사진만 올릴 수 있습니다.');
  expect(fetchFn).not.toHaveBeenCalled();
});
