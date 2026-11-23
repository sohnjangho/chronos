// CSV 가져오기·다른 프로젝트에서 복사(Task 77, 시안 ⑤). 서버는 Task 76 계약 꼴의 가짜다 — 미리 보기(dry_run=1)와 넣기(dry_run=0)는
// 같은 파일·같은 skip 을 받고, 화면은 서버가 준 판정·셈만 보인다. 사람·번호는 모두 가상(010-****-0000 꼴).
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { Role } from '../../os/session';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import { json } from '../../test-helpers';
import Contacts from './Contacts';
import css from './transfer.css?raw';
import type { CopySourceDetail, ImportOut, ImportRow } from './contactsApi';
import { contactCalls, stubContacts } from './testKit';

type Reply = { status: number; body: unknown };
interface Sent {
  method: string;
  url: string;
  file?: File | null;
  skip?: number[];
  body?: unknown;
}

const row = (over: Partial<ImportRow>): ImportRow => ({
  n: 2, company: '우리설비', name: '김설비', role_title: '설비 소장', phone_shown: '010-****-2222', phone_kind: 'mobile',
  do_not_contact: false, result: 'new', reason: null, code: null, column: null, skipped: false, ...over,
});

/** 시안 ⑤의 네 행: 새로 넣음 · 번호 없음 · 이미 있음 · 번호 형식 오류. */
const MOCKUP: ImportRow[] = [
  row({}),
  row({ n: 3, name: '오배관', role_title: '배관 기사', phone_shown: '번호 없음', phone_kind: null, result: 'no_phone' }),
  row({ n: 4, company: '대한골조', name: '박현장', role_title: '골조 팀장', phone_shown: '010-****-0000', result: 'exists', reason: '같은 번호가 이 프로젝트에 이미 있습니다.' }),
  row({ n: 5, company: '한빛전기', name: '이전기', role_title: '전기 과장', phone_shown: '01…', phone_kind: null, result: 'bad_phone', code: 'invalid_phone', reason: '전화번호 형식이 맞지 않습니다.' }),
];

/** Task 76 서버처럼: skip 에 든 행은 skipped, 셈은 skipped 를 빼고 센다. */
function answer(rows: ImportRow[], skip: number[]): ImportOut {
  const out = rows.map((r) => ({ ...r, skipped: skip.includes(r.n) }));
  const live = out.filter((r) => !r.skipped);
  const count = (...k: ImportRow['result'][]) => live.filter((r) => k.includes(r.result)).length;
  return {
    rows: out,
    summary: { new: count('new'), exists: count('exists'), no_phone: count('no_phone'), bad: count('bad_phone', 'bad_row'), skipped: out.length - live.length },
  };
}

let previewRows: ImportRow[];
let commitRows: ImportRow[] | null;
let importError: Reply | null;
let sources: Reply;
let source: CopySourceDetail;
let copyReply: Reply;
let sent: Sent[];

const SOURCE: CopySourceDetail = {
  schedule_id: 2,
  name: '가상 부품 공장',
  companies: [
    {
      id: 50, name: '대한골조', trade: '골조', people: [
        { id: 501, name: '박현장', role_title: '골조 팀장', phone_masked: '010-****-0000', phone_kind: 'mobile', has_phone: true, do_not_contact: false, already_here: true },
        { id: 502, name: '한골조', role_title: '골조 기사', phone_masked: '010-****-0003', phone_kind: 'mobile', has_phone: true, do_not_contact: false, already_here: false },
      ],
    },
    {
      id: 51, name: '가상도장', trade: '도장', people: [
        { id: 511, name: '도장반장', role_title: '도장 반장', phone_masked: '010-****-0004', phone_kind: 'mobile', has_phone: true, do_not_contact: true, already_here: false },
        { id: 512, name: '도장기사', role_title: '도장 기사', phone_masked: '번호 없음', phone_kind: null, has_phone: false, do_not_contact: false, already_here: false },
      ],
    },
  ],
};

function stub(role: Role = 'admin') {
  stubContacts(role);
  previewRows = MOCKUP;
  commitRows = null;
  importError = null;
  sources = { status: 200, body: [{ schedule_id: 2, name: '가상 부품 공장', people: 4 }, { schedule_id: 3, name: '빈 가상 현장', people: 0 }] };
  source = SOURCE;
  copyReply = { status: 200, body: { copied: 2, skipped: 0, refused: 1 } };
  sent = [];
  const inner = globalThis.fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? 'GET';
      if (url.startsWith('/api/schedules/1/contacts/import')) {
        const fd = init?.body as FormData;
        const skip = fd.getAll('skip').flatMap((s) => String(s).split(',')).filter(Boolean).map(Number);
        sent.push({ method, url, file: fd.get('file') as File | null, skip });
        if (importError) return json(importError.status, importError.body);
        const commit = url.endsWith('dry_run=0');
        return json(200, answer(commit && commitRows ? commitRows : previewRows, skip));
      }
      if (url.startsWith('/api/schedules/1/contacts/copy')) {
        sent.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
        if (url.endsWith('/copy-sources')) return json(sources.status, sources.body);
        if (url.endsWith('/copy-sources/2')) return json(200, source);
        return json(copyReply.status, copyReply.body);
      }
      return inner(input, init);
    }),
  );
}

beforeEach(() => {
  stub();
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
  localStorage.clear();
});

const show = () => render(<Contacts windowId="w1" params={{}} />);
const csvFile = (text = '협력사,이름,담당,전화번호\n우리설비,김설비,설비 소장,010-0000-2222\n', name = '연락처.csv') => new File([text], name, { type: 'text/csv' });
const dialog = (name: string | RegExp) => screen.getByRole('dialog', { name });
const imports = () => sent.filter((s) => s.url.includes('/import'));
const bookReads = () => contactCalls().filter((c) => c.method === 'GET' && c.url === '/api/schedules/1/contacts').length;

async function openImport() {
  show();
  await screen.findByText('박현장');
  await userEvent.click(screen.getByRole('button', { name: 'CSV 가져오기' }));
  return dialog('CSV 가져오기');
}

async function pick(file = csvFile()) {
  const d = dialog('CSV 가져오기');
  await userEvent.upload(within(d).getByLabelText('CSV 파일 고르기'), file);
  return d;
}

const table = () => within(dialog('CSV 가져오기')).getByRole('table', { name: '미리 보기' });
const tableRow = (n: number) => within(table()).getByRole('row', { name: new RegExp(`^${n}행`) });

describe('CSV import — preview before anything is written', () => {
  test('the encoding notice is always visible next to the file picker, and the address-book line no longer says 준비 중', async () => {
    const d = await openImport();
    expect(within(d).getByText('엑셀에서 저장한 CSV 는 한글이 깨질 수 있습니다 — 깨지면 UTF-8 로 저장해 주세요')).toBeVisible();
    expect(screen.queryByText(/준비 중입니다/)).toBeNull();
    expect(d).toHaveAttribute('aria-modal', 'true');
    expect(d.contains(document.activeElement)).toBe(true);
    await pick();
    expect(within(d).getByText('엑셀에서 저장한 CSV 는 한글이 깨질 수 있습니다 — 깨지면 UTF-8 로 저장해 주세요')).toBeVisible();
  });

  test('choosing a file asks for a preview (dry_run=1) with that file and shows the table and the summary', async () => {
    await openImport();
    const file = csvFile();
    const d = await pick(file);
    await within(d).findByRole('table', { name: '미리 보기' });
    expect(imports()).toEqual([{ method: 'POST', url: '/api/schedules/1/contacts/import?dry_run=1', file, skip: [] }]);
    expect(within(table()).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['행', '협력사', '이름', '담당', '전화번호', '결과', '빼기']);
    expect(within(tableRow(2)).getByText('새로 넣음')).toBeVisible();
    expect(within(tableRow(3)).getByText('번호 없음 · 넣되 보내기 불가')).toBeVisible();
    expect(within(tableRow(4)).getByText('이미 있음 · 건너뜀')).toBeVisible();
    expect(within(tableRow(4)).getByText('같은 번호가 이 프로젝트에 이미 있습니다.')).toBeVisible();
    expect(within(tableRow(5)).getByText('번호 형식 오류')).toBeVisible();
    expect(within(tableRow(2)).getByText('010-****-2222')).toBeVisible();
    expect(within(d).getByText('4행 중 2행 넣음 · 1행 건너뜀 · 1행 오류')).toBeVisible();
    expect(within(d).getByRole('button', { name: '2명 넣기' })).toBeEnabled();
  });

  test('an error row shows the server reason and the column, never the value, and is left out of the count', async () => {
    previewRows = [
      row({}),
      row({ n: 3, company: null, name: '오배관', phone_shown: '010-****-0005', result: 'bad_row', code: 'too_long', column: '협력사', reason: '글이 너무 깁니다(협력사·이름·공종·담당 100자, 메모 2000자까지).' }),
      row({ n: 4, name: '이전기', phone_shown: '01…', phone_kind: null, result: 'bad_phone', code: 'invalid_phone', reason: '주소록에 둘 수 없는 번호입니다.' }),
    ];
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    expect(within(tableRow(3)).getByText('「협력사」 칸 오류')).toBeVisible();
    expect(within(tableRow(3)).getByText('글이 너무 깁니다(협력사·이름·공종·담당 100자, 메모 2000자까지).')).toBeVisible();
    expect(within(tableRow(4)).getByText('01…')).toBeVisible();
    expect(within(tableRow(4)).getByText('주소록에 둘 수 없는 번호입니다.')).toBeVisible();
    expect(within(d).getByText('3행 중 1행 넣음 · 0행 건너뜀 · 2행 오류')).toBeVisible();
    expect(within(d).getByRole('button', { name: '1명 넣기' })).toBeEnabled();
  });

  test('do-not-contact and non-mobile numbers are labelled in the preview', async () => {
    previewRows = [row({ do_not_contact: true }), row({ n: 3, name: '이전기', phone_shown: '02-****-0000', phone_kind: 'landline' })];
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    expect(within(tableRow(2)).getByText('수신 거부')).toBeVisible();
    expect(within(tableRow(3)).getByText('유선')).toBeVisible();
  });

  test('removing a row with X puts its number in skip and asks again; the server answer decides the count; 되돌리기 takes it back', async () => {
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    await userEvent.click(within(tableRow(2)).getByRole('button', { name: '2행 빼기' }));
    await within(d).findByText('4행 중 1행 넣음 · 1행 건너뜀 · 1행 오류 · 1행 뺌');
    expect(imports().at(-1)).toMatchObject({ url: '/api/schedules/1/contacts/import?dry_run=1', skip: [2] });
    expect(imports().at(-1)!.file).toBe(imports()[0].file);
    expect(within(tableRow(2)).getByText('뺌')).toBeVisible();
    expect(within(d).getByRole('button', { name: '1명 넣기' })).toBeEnabled();
    await userEvent.click(within(tableRow(2)).getByRole('button', { name: '2행 되돌리기' }));
    await within(d).findByText('4행 중 2행 넣음 · 1행 건너뜀 · 1행 오류');
    expect(imports().at(-1)!.skip).toEqual([]);
  });

  test('n명 넣기 sends the same file and skip with dry_run=0, shows the server final counts and reloads the book', async () => {
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    await userEvent.click(within(tableRow(3)).getByRole('button', { name: '3행 빼기' }));
    await within(d).findByText(/1행 뺌/);
    // 그 사이 누가 김설비를 넣었다 — 서버는 다시 판정해 이미 있음으로 센다.
    commitRows = MOCKUP.map((r) => (r.n === 2 ? { ...r, result: 'exists', reason: '같은 번호가 이 프로젝트에 이미 있습니다.' } : r));
    const before = bookReads();
    await userEvent.click(within(d).getByRole('button', { name: '1명 넣기' }));
    expect(await within(d).findByText('0명 넣었습니다 · 2행 건너뜀 · 1행 오류 · 1행 뺌')).toBeVisible();
    expect(within(d).getByText('미리 본 뒤 주소록이 바뀌어 결과가 미리 보기와 다릅니다.')).toBeVisible();
    const commit = imports().at(-1)!;
    expect(commit).toMatchObject({ method: 'POST', url: '/api/schedules/1/contacts/import?dry_run=0', skip: [3] });
    expect(commit.file).toBe(imports()[0].file);
    await waitFor(() => expect(bookReads()).toBe(before + 1));
    expect(within(d).queryByRole('button', { name: /명 넣기/ })).toBeNull();
    await userEvent.click(within(d).getByRole('button', { name: '닫기' }));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('nothing is written before 넣기: Escape closes, focus returns to the button, and the file is gone when reopened', async () => {
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: 'CSV 가져오기' })).toHaveFocus();
    expect(imports().every((s) => s.url.endsWith('dry_run=1'))).toBe(true);
    const stored = JSON.stringify({ ...localStorage, ...sessionStorage });
    for (const s of ['김설비', '010-0000-2222', '연락처.csv', '2222']) expect(stored).not.toContain(s);
    await userEvent.click(screen.getByRole('button', { name: 'CSV 가져오기' }));
    expect(within(dialog('CSV 가져오기')).queryByRole('table')).toBeNull();
    expect(within(dialog('CSV 가져오기')).queryByText(/행 중/)).toBeNull();
  });

  test('a file that is not .csv or is over 1 MB is refused before any request', async () => {
    await openImport();
    const d = dialog('CSV 가져오기');
    fireEvent.change(within(d).getByLabelText('CSV 파일 고르기'), { target: { files: [new File(['x'], '연락처.xlsx')] } });
    expect(within(d).getByRole('alert')).toHaveTextContent('CSV 파일(.csv)만 고를 수 있습니다.');
    fireEvent.change(within(d).getByLabelText('CSV 파일 고르기'), { target: { files: [csvFile('a'.repeat(1024 * 1024 + 1))] } });
    expect(within(d).getByRole('alert')).toHaveTextContent('CSV 파일은 1MB 까지 올릴 수 있습니다.');
    expect(imports()).toHaveLength(0);
  });

  test('a file the server refuses shows its Korean message as it is and no table', async () => {
    importError = { status: 422, body: { code: 'csv_missing_column', message: 'CSV 파일 첫 줄에 「협력사」·「이름」 열이 있어야 합니다.', detail: { missing: ['협력사'] } } };
    await openImport();
    const d = await pick();
    expect(await within(d).findByRole('alert')).toHaveTextContent('CSV 파일 첫 줄에 「협력사」·「이름」 열이 있어야 합니다.');
    expect(within(d).queryByRole('table')).toBeNull();
    expect(within(d).queryByRole('button', { name: /명 넣기/ })).toBeNull();
  });

  test('200 rows scroll inside the dialog while the title, summary and buttons stay outside the scroller', async () => {
    previewRows = Array.from({ length: 200 }, (_, i) =>
      row({ n: i + 2, name: i === 0 ? '아주아주긴이름을가진가상의현장담당자전기통신소방설비' : `가상${i}`, phone_shown: `010-****-${String(i).padStart(4, '0')}`, ...(i % 20 === 5 ? { result: 'bad_phone', code: 'invalid_phone', reason: '전화번호 형식이 맞지 않습니다.', phone_shown: '01…' } : {}) }),
    );
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    expect(within(table()).getAllByRole('row')).toHaveLength(201);
    const scroller = table().closest('.ct-xfer-scroll')!;
    expect(scroller).not.toBeNull();
    expect(scroller.contains(within(d).getByText('200행 중 190행 넣음 · 0행 건너뜀 · 10행 오류'))).toBe(false);
    expect(scroller.contains(within(d).getByRole('button', { name: '190명 넣기' }))).toBe(false);
    expect(scroller.contains(within(d).getByRole('heading', { name: 'CSV 가져오기' }))).toBe(false);
    const long = within(table()).getByText('아주아주긴이름을가진가상의현장담당자전기통신소방설비');
    expect(long).toHaveClass('ct-ellipsis');
    expect(long).toHaveAttribute('title', '아주아주긴이름을가진가상의현장담당자전기통신소방설비');
    expect(css).toMatch(/\.ct-xfer\s*\{[^}]*max-height:\s*100%/);
    expect(css).toMatch(/\.ct-xfer\s*\{[^}]*display:\s*flex/);
    expect(css).toMatch(/\.ct-xfer-scroll\s*\{[^}]*overflow-y:\s*auto/);
    expect(css).toMatch(/\.ct-xfer-scroll\s*\{[^}]*min-height:\s*0/);
    expect(css).toMatch(/\.ct-xfer-tbl thead th\s*\{[^}]*position:\s*sticky/);
  });

  test('오류만 보기 shows the error rows only, with their count', async () => {
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    await userEvent.click(within(d).getByRole('checkbox', { name: '오류만 보기 (1행)' }));
    expect(within(table()).getAllByRole('row')).toHaveLength(2);
    expect(tableRow(5)).toBeVisible();
  });

  test('a project switch closes the dialog and drops the file', async () => {
    await openImport();
    const d = await pick();
    await within(d).findByRole('table', { name: '미리 보기' });
    act(() => useCurrentSchedule.getState().setCurrent({ id: 2, name: '가상 부품 공장' }));
    await screen.findByText(/아직 주소록이 비어 있습니다/);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('copy from another project', () => {
  test('a user has no copy button (CSV import stays)', async () => {
    stub('user');
    show();
    await screen.findByText('박현장');
    expect(screen.queryByRole('button', { name: /다른 프로젝트에서 복사/ })).toBeNull();
    expect(screen.getByRole('button', { name: 'CSV 가져오기' })).toBeEnabled();
  });

  async function openCopy() {
    show();
    await screen.findByText('박현장');
    await userEvent.click(screen.getByRole('button', { name: '다른 프로젝트에서 복사' }));
    const d = dialog('다른 프로젝트에서 복사');
    await within(d).findByRole('option', { name: '가상 부품 공장 · 4명' });
    return d;
  }

  test('an admin picks a project, then people by company; already-here people cannot be chosen; the server counts are shown', async () => {
    const d = await openCopy();
    expect(within(d).getByText('복사한 뒤에는 서로 따로 고칩니다.')).toBeVisible();
    expect(within(d).getByRole('option', { name: '빈 가상 현장 · 0명' })).toBeDisabled();
    await userEvent.selectOptions(within(d).getByRole('combobox', { name: '복사해 올 프로젝트' }), '2');
    const co = await within(d).findByRole('group', { name: '대한골조' });
    expect(within(co).getByRole('checkbox', { name: /박현장/ })).toBeDisabled();
    expect(within(co).getByText('이미 있음')).toBeVisible();
    const dnc = within(d).getByRole('group', { name: '가상도장' });
    expect(within(dnc).getByText('수신 거부')).toBeVisible();
    expect(within(d).getByText('수신 거부인 사람은 복사한 뒤에도 연락할 수 없습니다.')).toBeVisible();
    expect(within(co).getByText('010-****-0003')).toBeVisible();
    await userEvent.click(within(co).getByRole('checkbox', { name: /^한골조/ }));
    await userEvent.click(within(dnc).getByRole('checkbox', { name: /도장반장/ }));
    const before = bookReads();
    await userEvent.click(within(d).getByRole('button', { name: '2명 복사해 오기' }));
    expect(await within(d).findByText('2명 복사함 · 0명 건너뜀(이미 있음) · 1명 거절')).toBeVisible();
    expect(sent.at(-1)).toEqual({ method: 'POST', url: '/api/schedules/1/contacts/copy', body: { from_schedule_id: 2, contact_ids: [502, 511] } });
    await waitFor(() => expect(bookReads()).toBe(before + 1));
  });

  test('search narrows people, and choosing a whole company skips already-here people', async () => {
    const d = await openCopy();
    await userEvent.selectOptions(within(d).getByRole('combobox', { name: '복사해 올 프로젝트' }), '2');
    await within(d).findByRole('group', { name: '대한골조' });
    await userEvent.click(within(d).getByRole('checkbox', { name: '대한골조 모두 고르기' }));
    expect(within(d).getByRole('button', { name: '1명 복사해 오기' })).toBeEnabled();
    await userEvent.type(within(d).getByRole('searchbox', { name: '이름·담당·협력사 찾기' }), '기사');
    expect(within(d).queryByText('도장반장')).toBeNull();
    expect(within(d).getByText('도장기사')).toBeVisible();
    expect(within(d).getByText('한골조')).toBeVisible();
  });

  test('a 403 from the server is shown as its message', async () => {
    sources = { status: 403, body: { code: 'admin_only', message: '관리자만 할 수 있습니다.' } };
    show();
    await screen.findByText('박현장');
    await userEvent.click(screen.getByRole('button', { name: '다른 프로젝트에서 복사' }));
    expect(await within(dialog('다른 프로젝트에서 복사')).findByRole('alert')).toHaveTextContent('관리자만 할 수 있습니다.');
  });

  test('Escape closes the copy dialog and focus returns to its button', async () => {
    await openCopy();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: '다른 프로젝트에서 복사' })).toHaveFocus();
  });
});
