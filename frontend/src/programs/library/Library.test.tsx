// 자료함 프로그램 시험: 필터 조합 · 찾기 · 상세·미리 보기 · 축 고치기 · 지우기 권한 · 합치기(관리자) · 진행률 · 200개 쪽 나눔.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { useWindows } from '../../os/windowStore';
import Library from './Library';
import {
  countGets,
  lastQuery,
  many,
  mockList,
  mockPreview,
  mockReindex,
  paged,
  PHOTO,
  RUNNING,
  SHEET,
  SPEC,
  stubLibrary,
  writes,
} from './testKit';

beforeEach(() => {
  localStorage.clear();
  if (!('createObjectURL' in URL)) {
    Object.defineProperty(URL, 'createObjectURL', { writable: true, value: () => '' });
  }
  if (!('revokeObjectURL' in URL)) {
    Object.defineProperty(URL, 'revokeObjectURL', { writable: true, value: () => {} });
  }
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fake-url');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('loads axes, files, and sends combined facet queries and search', async () => {
  stubLibrary();
  render(<Library />);

  expect(await screen.findByRole('option', { name: new RegExp(SPEC.name) })).toBeVisible();
  expect(screen.getAllByText('새').length).toBeGreaterThanOrEqual(1);

  const facetNav = screen.getByRole('complementary', { name: '분류 필터' });
  await userEvent.click(within(facetNav).getByLabelText(/시방서/));
  await userEvent.click(within(facetNav).getByLabelText(/^골조\d/));

  await waitFor(() => {
    const q = lastQuery();
    expect(q.getAll('종류')).toEqual(['시방서']);
    expect(q.getAll('공종')).toEqual(['골조']);
  });

  const searchInput = screen.getByRole('searchbox', { name: '자료 찾기' });
  await userEvent.type(searchInput, '동절기 양생');
  await userEvent.click(screen.getByRole('button', { name: '찾기' }));

  await waitFor(() => expect(lastQuery().get('q')).toBe('동절기 양생'));
});

test('shows preview for PDF, image, and sheet top 20 rows, and opens chat with attach param', async () => {
  stubLibrary();
  mockPreview((id, p) => {
    if (id === SPEC.file_id) return { kind: 'pdf', page: p, pages: 2, text: `쪽 ${p} 본문` };
    if (id === SHEET.file_id) {
      const rows = Array.from({ length: 25 }, (_, i) => `행${i + 1},값${i + 1}`).join('\n');
      return { kind: 'sheet', page: 1, pages: 1, text: rows };
    }
    return { text: '' };
  });
  const openSpy = vi.spyOn(useWindows.getState(), 'open');

  render(<Library />);
  const detail = await screen.findByRole('region', { name: '자료 상세' });
  expect(await within(detail).findByText('쪽 1 본문')).toBeVisible();

  await userEvent.click(within(detail).getByRole('button', { name: '다음 쪽' }));
  expect(await within(detail).findByText('쪽 2 본문')).toBeVisible();

  await userEvent.click(within(detail).getByRole('button', { name: '대화에 붙이기' }));
  expect(openSpy).toHaveBeenCalledWith('chat', { attach: String(SPEC.file_id) });

  // 사진 미리 보기
  await userEvent.click(screen.getByRole('option', { name: new RegExp(PHOTO.name) }));
  expect(await within(detail).findByRole('img', { name: PHOTO.name })).toHaveAttribute('src', 'blob:fake-url');

  // 표 앞 20행 제한
  await userEvent.click(screen.getByRole('option', { name: new RegExp(SHEET.name) }));
  expect(await within(detail).findByText(/앞 20행만 미리 보입니다/)).toBeVisible();
  expect(within(detail).queryByText(/행25/)).toBeNull();
});

test('patches axes when adding or removing a value', async () => {
  stubLibrary();
  render(<Library />);
  const detail = await screen.findByRole('region', { name: '자료 상세' });
  await within(detail).findByText(SPEC.name);

  const input = within(detail).getByLabelText('공종 값 추가');
  await userEvent.type(input, '철근{enter}');

  await waitFor(() => {
    const patch = writes().find((w) => w.method === 'PATCH');
    expect(patch?.url).toBe(`/api/files/${SPEC.file_id}/axes`);
    expect(patch?.body).toEqual({ 공종: ['골조', '철근'] });
  });
});

test('enforces delete and purge permissions by role and owner', async () => {
  // 일반 사용자(id=2): PHOTO(uploaded_by=2)는 지우기 가능, SPEC(uploaded_by=1)은 불가, 완전히 지우기 늘 불가
  stubLibrary({ role: 'user', userId: 2 });
  render(<Library />);
  const detail = await screen.findByRole('region', { name: '자료 상세' });
  await within(detail).findByText(SPEC.name);
  expect(within(detail).queryByRole('button', { name: '지우기' })).toBeNull();
  expect(within(detail).queryByRole('button', { name: '완전히 지우기' })).toBeNull();
  // 일반 사용자는 합치기 제안을 부르지 않는다
  expect(countGets('/api/files/merge-suggestions')).toBe(0);

  await userEvent.click(screen.getByRole('option', { name: new RegExp(PHOTO.name) }));
  expect(await within(detail).findByRole('button', { name: '지우기' })).toBeVisible();
  expect(within(detail).queryByRole('button', { name: '완전히 지우기' })).toBeNull();

  await userEvent.click(within(detail).getByRole('button', { name: '지우기' }));
  await userEvent.click(within(detail).getByRole('button', { name: '지우기 확인' }));
  await waitFor(() => {
    const del = writes().find((w) => w.method === 'DELETE');
    expect(del?.url).toBe(`/api/files/${PHOTO.file_id}`);
  });
});

test('admin sees merge suggestions, purge button, and running reindex progress', async () => {
  stubLibrary({ role: 'admin', userId: 1 });
  mockReindex(RUNNING);
  render(<Library />);

  expect(await screen.findByRole('progressbar')).toBeVisible();
  expect(screen.getByText(/다시 넣는 중 53%/)).toBeVisible();

  const mergeBox = await screen.findByRole('region', { name: '분류 값 합치기 제안' });
  await userEvent.click(within(mergeBox).getByRole('button', { name: '제안 보기' }));
  const mergeBtns = within(mergeBox).getAllByRole('button', { name: '합치기' });
  await userEvent.click(mergeBtns[0]);

  await waitFor(() => {
    const post = writes().find((w) => w.method === 'POST' && w.url === '/api/files/merge');
    expect(post?.body).toEqual({ axis: '공종', from: ['골조공사'], to: '골조' });
  });

  const detail = screen.getByRole('region', { name: '자료 상세' });
  expect(within(detail).getByRole('button', { name: '완전히 지우기' })).toBeVisible();
});

test('paginates 200 items 50 per page and remembers detail width per user', async () => {
  stubLibrary({ role: 'admin', userId: 7 });
  mockList(paged(many(200)));
  render(<Library />);

  expect(await screen.findByText('전체 200건')).toBeVisible();
  expect(screen.getAllByRole('option')).toHaveLength(50);
  expect(screen.getByText('1 / 4쪽')).toBeVisible();

  await userEvent.click(screen.getByRole('button', { name: '다음' }));
  expect(await screen.findByText('2 / 4쪽')).toBeVisible();
  expect(lastQuery().get('page')).toBe('2');

  const splitter = screen.getByRole('separator', { name: '미리 보기 폭 조절' });
  splitter.focus();
  await userEvent.keyboard('{ArrowLeft}');
  expect(localStorage.getItem('chronos.library.detailWidth.7')).toBe('464');
});
