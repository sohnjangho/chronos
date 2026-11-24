// 설정 → 화면 → 「배경」: 그림 고르기(이름·미리보기), 내 사진 올리기·바꾸기·지우기, 사진(그림 파일)일 때만 배치 방식 5가지.
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { setWallpaperFileOverrides } from '../../os/wallpapers';
import { useWallpaper } from '../../os/wallpaperStore';
import { useTheme } from '../../os/theme';
import { json, signInAsDemo, stubFetch } from '../../test-helpers';
import WallpaperCard from './WallpaperCard';

const w = () => useWallpaper.getState();
let photoStored: boolean;

beforeEach(() => {
  localStorage.clear();
  photoStored = false;
  signInAsDemo('user');
  w().reset();
  w().load(1);
  useTheme.getState().load(1);
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:photo-1'), revokeObjectURL: vi.fn() }));
  stubFetch({
    '/api/me/ui-state': {},
    'PUT /api/me/ui-state/appearance': () => json(200, { mode: 'appearance', updated_at: new Date().toISOString() }),
    '/api/me/wallpaper': () =>
      photoStored
        ? new Response(new Blob([new Uint8Array([1])], { type: 'image/png' }), { status: 200 })
        : json(404, { code: 'wallpaper_none', message: '올린 사진이 없습니다.', detail: null }),
    'PUT /api/me/wallpaper': () => {
      photoStored = true;
      return json(200, { type: 'image/png', width: 4, height: 3, bytes: 1, updated_at: new Date().toISOString() });
    },
    'DELETE /api/me/wallpaper': () => {
      photoStored = false;
      return new Response(null, { status: 204 });
    },
  });
});
afterEach(() => {
  setWallpaperFileOverrides(null);
  vi.unstubAllGlobals();
});

const card = () => screen.getByRole('region', { name: '바탕화면 배경' });
const tile = (name: string) => within(card()).getByRole('button', { name: new RegExp(`^${name}`) });
const preview = () => screen.getByTestId('wallpaper-preview-layer');

test('기본·8종·내 사진이 이름과 함께 보이고, 고르면 미리보기와 저장이 바뀐다', async () => {
  render(<WallpaperCard />);
  for (const name of ['기본', '프리즘 공정', '네트워크 궤도', '지형 등고선', '정밀 격자', '스컬프처 모노', '크로노스 성좌', '미니멀 웜', '미니멀 쿨', '내 사진']) {
    expect(tile(name)).toBeVisible();
  }
  expect(tile('기본')).toHaveAttribute('aria-pressed', 'true');
  await userEvent.click(tile('지형 등고선'));
  expect(tile('지형 등고선')).toHaveAttribute('aria-pressed', 'true');
  expect(w().wallpaper).toBe('contours');
  expect(preview().style.backgroundImage).toContain('contours-light');
  expect(JSON.parse(localStorage.getItem('chronos.wallpaper.1')!).state.wallpaper).toBe('contours');
  // 테마를 바꾸면 그 판으로
  act(() => useTheme.getState().setTheme('dark'));
  expect(preview().style.backgroundImage).toContain('contours-dark');
  // SVG 그림은 늘 채우기 — 배치 방식 고르기는 없다
  expect(within(card()).queryByRole('radiogroup', { name: '배치 방식' })).toBeNull();
});

test('내 사진: 올리면 고르고 배치 방식 5가지가 보이며, 바꾸면 미리보기 CSS 가 바뀐다', async () => {
  render(<WallpaperCard />);
  const input = within(card()).getByLabelText('사진 올리기');
  await userEvent.upload(input, new File([new Uint8Array([1])], 'x.png', { type: 'image/png' }));
  await waitFor(() => expect(tile('내 사진')).toHaveAttribute('aria-pressed', 'true'));
  const group = within(card()).getByRole('radiogroup', { name: '배치 방식' });
  expect(within(group).getAllByRole('radio').map((r) => r.textContent)).toEqual(['채우기', '맞추기', '늘이기', '바둑판', '가운데']);
  await waitFor(() => expect(preview().style.backgroundImage).toBe('url("blob:photo-1")'));
  expect(preview().style.backgroundSize).toBe('cover');
  const expected: [string, string, string][] = [
    ['맞추기', 'contain', 'no-repeat'],
    ['늘이기', '100% 100%', 'no-repeat'],
    ['바둑판', 'auto', 'repeat'],
    ['가운데', 'auto', 'no-repeat'],
    ['채우기', 'cover', 'no-repeat'],
  ];
  for (const [name, size, repeat] of expected) {
    await userEvent.click(within(group).getByRole('radio', { name }));
    expect(within(group).getByRole('radio', { name })).toHaveAttribute('aria-checked', 'true');
    expect(preview().style.backgroundSize).toBe(size);
    expect(preview().style.backgroundRepeat).toBe(repeat);
  }
  expect(within(card()).getByLabelText('사진 바꾸기')).toBeInTheDocument();
  await userEvent.click(within(card()).getByRole('button', { name: '사진 지우기' }));
  await waitFor(() => expect(tile('기본')).toHaveAttribute('aria-pressed', 'true'));
  expect(within(card()).queryByRole('button', { name: '사진 지우기' })).toBeNull();
});

test('너무 큰 사진·다른 형식은 한국어로 알린다', async () => {
  render(<WallpaperCard />);
  const input = within(card()).getByLabelText('사진 올리기');
  await userEvent.upload(input, new File([new Uint8Array(10 * 1024 * 1024 + 1)], 'big.jpg', { type: 'image/jpeg' }));
  expect(await within(card()).findByRole('alert')).toHaveTextContent('사진이 너무 큽니다. 10MB 까지 올릴 수 있습니다.');
  // accept 를 지나 들어온 다른 형식도 막는다
  await userEvent.upload(input, new File([new Uint8Array([1])], 'a.gif', { type: 'image/gif' }), { applyAccept: false });
  expect(await within(card()).findByRole('alert')).toHaveTextContent('JPG·PNG·WebP 사진만 올릴 수 있습니다.');
  expect(w().wallpaper).toBe('default');
});

test('그림 파일 자리(jpg 등)를 넣은 테마는 그 그림을 쓰고 배치 방식도 고를 수 있다', async () => {
  setWallpaperFileOverrides({ 'orbits-light.svg': '/o-l.svg', 'orbits-dark.svg': '/o-d.svg', 'orbits-light.jpg': '/o-l.jpg' });
  render(<WallpaperCard />);
  await userEvent.click(tile('네트워크 궤도'));
  expect(preview().style.backgroundImage).toBe('url("/o-l.jpg")');
  const group = within(card()).getByRole('radiogroup', { name: '배치 방식' });
  await userEvent.click(within(group).getByRole('radio', { name: '바둑판' }));
  expect(preview().style.backgroundRepeat).toBe('repeat');
});

test('내 사진을 골랐는데 사진이 없으면 안내한다', async () => {
  localStorage.setItem('chronos.wallpaper.1', JSON.stringify({ state: { v: 1, wallpaper: 'photo', fit: 'fill' }, at: 0, dirty: false }));
  w().load(1);
  render(<WallpaperCard />);
  expect(await within(card()).findByText('올린 사진이 없습니다 — 사진을 올리거나 다른 배경을 고르세요')).toBeVisible();
  expect(within(card()).queryByText(/그림 테마는 늘 화면을 채웁니다/)).toBeNull();
});

test('사진을 못 받으면 다시 시도할 수 있다', async () => {
  let fail = true;
  photoStored = true;
  stubFetch({
    '/api/me/wallpaper': () => (fail ? Promise.reject(new TypeError('offline')) : new Response(new Blob([new Uint8Array([1])]), { status: 200 })),
  });
  localStorage.setItem('chronos.wallpaper.1', JSON.stringify({ state: { v: 1, wallpaper: 'photo', fit: 'fill' }, at: 0, dirty: false }));
  w().load(1);
  render(<WallpaperCard />);
  expect(await within(card()).findByRole('alert')).toHaveTextContent('사진을 불러오지 못했습니다');
  fail = false;
  await userEvent.click(within(card()).getByRole('button', { name: '다시 시도' }));
  await waitFor(() => expect(preview().style.backgroundImage).toBe('url("blob:photo-1")'));
  expect(within(card()).queryByRole('alert')).toBeNull();
});

test('올리는 동안에는 그림·배치 방식을 고를 수 없다', async () => {
  let release!: (r: Response) => void;
  setWallpaperFileOverrides({ 'orbits-light.jpg': '/o.jpg' });
  stubFetch({
    '/api/me/wallpaper': () => json(404, { code: 'wallpaper_none', message: '올린 사진이 없습니다.', detail: null }),
    'PUT /api/me/wallpaper': () => new Promise<Response>((r) => (release = r)),
    'PUT /api/me/ui-state/appearance': () => json(200, { mode: 'appearance', updated_at: new Date().toISOString() }),
  });
  w().choose('orbits');
  render(<WallpaperCard />);
  await userEvent.upload(within(card()).getByLabelText('사진 올리기'), new File([new Uint8Array([1])], 'x.png', { type: 'image/png' }));
  await waitFor(() => expect(tile('기본')).toBeDisabled());
  for (const name of ['프리즘 공정', '미니멀 쿨', '내 사진']) expect(tile(name)).toBeDisabled();
  for (const r of within(card()).getAllByRole('radio')) expect(r).toBeDisabled();
  release(json(200, { type: 'image/png', width: 1, height: 1, bytes: 1, updated_at: new Date().toISOString() }));
  await waitFor(() => expect(tile('기본')).toBeEnabled());
  expect(tile('내 사진')).toHaveAttribute('aria-pressed', 'true');
});
