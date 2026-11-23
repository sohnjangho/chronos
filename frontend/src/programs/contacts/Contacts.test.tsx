// 연락처 프로그램(Task 75): 협력사별 묶음·찾기 / 50명 넘침 없음 / 사람 추가 본문 / 가린 번호·눌러서 보기·닫으면 다시 가림 /
// 번호 종류·잠긴 채널 / 수신 거부 풀기 403·번호 바꾸기 안내와 확인 / 보기 한도 / 현장 관리자 / params.contact / 시험 모드 띠.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { programs, register } from '../../os/registry';
import { useCurrentSchedule } from '../../os/currentSchedule';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Contacts from './Contacts';
import css from './contacts.css?raw';
import manifest from './index';
import {
  bigBook, BOOK, contactCalls, detail, EMPTY, JUNG, lastWrite, LEE, mockBook, mockDetail, mockReveal, mockStatus, mockWrite, PARK,
  reveals, STATUS, stubContacts, writes,
} from './testKit';

beforeEach(() => {
  stubContacts();
  useWindows.setState({ open: vi.fn(), setTitle: vi.fn() } as never);
  useCurrentSchedule.setState({ current: { id: 1, name: '5층 사무동 신축' } });
});
afterEach(() => {
  cleanup();
  useCurrentSchedule.setState({ current: null });
  useUiContext.getState().reset();
  vi.unstubAllGlobals();
});

const show = (params: Record<string, string> = {}) => render(<Contacts windowId="w1" params={params} />);
const book = () => screen.getByRole('navigation', { name: '주소록' });
const company = (name: string) => within(book()).getByRole('group', { name });
const row = (name: string | RegExp) => within(book()).getByRole('button', { name: typeof name === 'string' ? new RegExp(name) : name });
const form = () => screen.getByRole('form');

async function openEdit(name: string) {
  show();
  await userEvent.click(await screen.findByRole('button', { name: new RegExp(name) }));
  await userEvent.click(screen.getByRole('button', { name: '고치기' }));
  await screen.findByRole('form', { name: '사람 고치기' });
}

test('the manifest is 연락처, a work program at 1280×820, hidden from field managers', () => {
  expect(manifest).toMatchObject({ id: 'contacts', name: '연락처', kind: 'work', noField: true, defaultSize: { w: 1280, h: 820 } });
  register(manifest);
  expect(programs('field').map((p) => p.id)).not.toContain('contacts');
  expect(programs('user').map((p) => p.id)).toContain('contacts');
  expect(programs('admin').map((p) => p.id)).toContain('contacts');
});

describe('address book', () => {
  test('people are grouped by company and the window publishes its context', async () => {
    show();
    await screen.findByText('박현장');
    expect(within(company('대한골조')).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      expect.stringContaining('박현장'), expect.stringContaining('최반장'),
    ]);
    expect(within(company('한빛전기')).getByText('이전기')).toBeVisible();
    expect(useUiContext.getState().byWindow.w1).toEqual({ program: 'contacts', schedule_id: 1 });
    expect(contactCalls().some((c) => c.url === '/api/schedules/1/contacts')).toBe(true);
  });

  test('search matches name and role and hides empty companies', async () => {
    show();
    await screen.findByText('박현장');
    await userEvent.type(screen.getByRole('searchbox', { name: '이름·담당 찾기' }), '전기 기사');
    expect(within(book()).queryByText('박현장')).toBeNull();
    expect(within(book()).queryByRole('group', { name: '대한골조' })).toBeNull();
    expect(row('정배선')).toBeVisible();
    await userEvent.clear(screen.getByRole('searchbox', { name: '이름·담당 찾기' }));
    await userEvent.type(screen.getByRole('searchbox', { name: '이름·담당 찾기' }), '최반');
    expect(row('최반장')).toBeVisible();
    expect(within(book()).queryByText('정배선')).toBeNull();
    await userEvent.type(screen.getByRole('searchbox', { name: '이름·담당 찾기' }), '없는사람');
    expect(screen.getByText('찾는 사람이 없습니다.')).toBeVisible();
  });

  test('row badges: unread, no number, do-not-contact, bad number and non-mobile kind', async () => {
    show();
    await screen.findByText('박현장');
    expect(row('박현장')).toHaveAccessibleName(/새 회신 1/);
    expect(within(row('최반장')).getByText('번호 없음')).toBeVisible();
    expect(within(row('정배선')).getByText('수신 거부')).toBeVisible();
    expect(within(row('김설비')).getByText('번호 오류')).toBeVisible();
    expect(within(row('김설비')).getByText('대표번호')).toBeVisible();
    expect(within(row('이전기')).getByText('유선')).toBeVisible();
    expect(within(row('박현장')).queryByText('휴대전화')).toBeNull();
  });

  test('fifty people across eight companies stay inside the list (no overflow)', async () => {
    mockBook(bigBook());
    show();
    await screen.findByText('아주아주긴이름을가진가상의현장담당자0');
    expect(within(book()).getAllByRole('group')).toHaveLength(8);
    expect(within(book()).getAllByRole('listitem')).toHaveLength(50);
    // 긴 이름·담당은 한 줄로 자르고(…), 목록만 세로로 스크롤한다. 칸은 줄어들 수 있다(min-width 0).
    const long = screen.getByText('아주아주긴이름을가진가상의현장담당자0');
    expect(long).toHaveClass('ct-ellipsis');
    expect(screen.getAllByText('전기·통신·소방 설비 총괄 현장 대리인 겸 안전 관리 책임자')[0]).toHaveClass('ct-ellipsis');
    expect(css).toMatch(/\.ct-ellipsis\s*\{[^}]*text-overflow:\s*ellipsis/);
    expect(css).toMatch(/\.ct-book-list\s*\{[^}]*overflow-y:\s*auto/);
    expect(css).toMatch(/\.ct-root\s*\{[^}]*overflow:\s*hidden/);
    // 묶음은 접을 수 있다.
    await userEvent.click(within(book()).getByRole('button', { name: /가상협력사2 6명/ }));
    expect(within(company('가상협력사2')).queryAllByRole('listitem')).toHaveLength(0);
  });

  test('an empty project explains where to start and locks adding people', async () => {
    mockBook(EMPTY);
    show();
    expect(await screen.findByText(/아직 주소록이 비어 있습니다/)).toBeVisible();
    expect(screen.getByRole('button', { name: '+ 사람 추가' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '협력사 추가' })).toBeEnabled();
  });

  test('copy from another project is shown to admins only; hidden people come back on request', async () => {
    show();
    await screen.findByText('박현장');
    expect(screen.getByRole('button', { name: /다른 프로젝트에서 복사/ })).toBeVisible();
    await userEvent.click(screen.getByRole('checkbox', { name: '숨긴 사람 보기' }));
    await waitFor(() => expect(contactCalls().some((c) => c.url === '/api/schedules/1/contacts?include_hidden=true')).toBe(true));
    cleanup();
    stubContacts('user');
    show();
    await screen.findByText('박현장');
    expect(screen.queryByRole('button', { name: /다른 프로젝트에서 복사/ })).toBeNull();
  });

  test('params.contact selects that person and shows the masked number with its kind', async () => {
    show({ contact: String(LEE.id), tab: 'calls' });
    const head = await screen.findByRole('heading', { name: '이전기' });
    const pane = head.closest('section')!;
    expect(within(pane).getByText(/02-\*\*\*\*-0000/)).toBeVisible();
    expect(within(pane).getByText('유선')).toBeVisible();
    expect(row('이전기')).toHaveAttribute('aria-current', 'true');
    expect(within(pane).getByRole('region', { name: '대화' })).toHaveAttribute('data-tab', 'calls');
  });
});

describe('notify status strip', () => {
  test('test mode shows the allow-list count', async () => {
    show();
    expect(await screen.findByText('시험 모드 · 허용 번호 1개')).toBeVisible();
  });

  test('without the status route the strip is neutral and the program still works', async () => {
    mockStatus(null, 404);
    show();
    expect(await screen.findByText('알림 연결 설정 전')).toBeVisible();
    expect(await screen.findByText('박현장')).toBeVisible();
  });

  test('a connection that is not ready is neutral too', async () => {
    mockStatus({ ...STATUS, ready: false });
    show();
    expect(await screen.findByText('알림 연결 설정 전')).toBeVisible();
  });
});

describe('person form', () => {
  test('adding a person posts hours, gender and language', async () => {
    show();
    await screen.findByText('박현장');
    await userEvent.click(screen.getByRole('button', { name: '+ 사람 추가' }));
    const f = await screen.findByRole('form', { name: '사람 추가' });
    await userEvent.type(within(f).getByLabelText('이름'), '오배관');
    await userEvent.type(within(f).getByLabelText('담당'), '배관 기사');
    await userEvent.selectOptions(within(f).getByLabelText('협력사'), '우리설비');
    await userEvent.type(within(f).getByLabelText('전화번호'), '010-0000-0002');
    const hours = within(f).getByRole('group', { name: '근무시간' });
    expect(within(hours).getByText(/프로젝트 기본/)).toBeVisible();
    await userEvent.click(within(hours).getByRole('button', { name: '월' }));
    await userEvent.click(within(hours).getByRole('button', { name: '화' }));
    await userEvent.clear(within(hours).getByLabelText('시작'));
    await userEvent.type(within(hours).getByLabelText('시작'), '07:00');
    await userEvent.click(within(f).getByRole('radio', { name: '여' }));
    await userEvent.selectOptions(within(f).getByLabelText('언어'), 'vi');
    await userEvent.click(within(f).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(lastWrite()?.method).toBe('POST'));
    expect(lastWrite()).toEqual({
      method: 'POST',
      url: '/api/schedules/1/contacts/people',
      body: {
        name: '오배관', role_title: '배관 기사', company_id: 30, phone: '010-0000-0002',
        hours: { days: [0, 1], start: '07:00', end: '18:00' }, gender: 'female', language: 'vi', voice_mode: 'auto',
        do_not_contact: false, note: '',
      },
    });
  });

  test('hours left empty means project default (null) and the kakao box is locked with a reason', async () => {
    show();
    await screen.findByText('박현장');
    await userEvent.click(screen.getByRole('button', { name: '+ 사람 추가' }));
    const f = await screen.findByRole('form', { name: '사람 추가' });
    const kakao = within(f).getByRole('checkbox', { name: '카카오톡' });
    expect(kakao).toBeDisabled();
    expect(within(f).getByText(/카카오톡은 채널·문안 승인 뒤 쓸 수 있습니다/)).toBeVisible();
    await userEvent.type(within(f).getByLabelText('이름'), '한사람');
    await userEvent.click(within(f).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(lastWrite()?.method).toBe('POST'));
    expect(lastWrite()?.body).toMatchObject({ name: '한사람', company_id: 10, phone: null, hours: null });
    expect(lastWrite()?.body).not.toHaveProperty('can_kakao');
  });

  test('the number is masked; 눌러서 보기 reveals it and closing the form masks it again', async () => {
    await openEdit('박현장');
    expect(within(form()).getByText('010-****-0000')).toBeVisible();
    expect(screen.queryByDisplayValue('010-0000-0000')).toBeNull();
    await userEvent.click(within(form()).getByRole('button', { name: '눌러서 보기' }));
    expect(await within(form()).findByDisplayValue('010-0000-0000')).toBeVisible();
    expect(reveals()).toHaveLength(1);
    expect(reveals()[0].url).toBe('/api/schedules/1/contacts/people/1/reveal');
    await userEvent.click(within(form()).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('form')).toBeNull();
    expect(screen.queryByText('010-0000-0000')).toBeNull();
    expect(screen.queryByDisplayValue('010-0000-0000')).toBeNull();
    expect(JSON.stringify(localStorage)).not.toContain('0000-0000');
    await userEvent.click(screen.getByRole('button', { name: '고치기' }));
    expect(within(await screen.findByRole('form')).getByText('010-****-0000')).toBeVisible();
    expect(screen.queryByDisplayValue('010-0000-0000')).toBeNull();
  });

  test('the reveal limit shows the server reason and is not retried', async () => {
    mockReveal(429, { code: 'too_many_reveals', message: '번호 보기는 10분에 30번까지입니다. 잠시 뒤에 다시 해 주세요.' });
    await openEdit('박현장');
    await userEvent.click(within(form()).getByRole('button', { name: '눌러서 보기' }));
    expect(await within(form()).findByText('번호 보기는 10분에 30번까지입니다. 잠시 뒤에 다시 해 주세요.')).toBeVisible();
    await new Promise((r) => setTimeout(r, 30));
    expect(reveals()).toHaveLength(1);
  });

  test('a landline shows its kind and the SMS box is locked with the reason', async () => {
    mockDetail(detail(LEE));
    await openEdit('이전기');
    const f = form();
    expect(within(f).getByText('유선')).toBeVisible();
    expect(within(f).getByRole('checkbox', { name: '문자' })).toBeDisabled();
    expect(within(f).getByRole('checkbox', { name: '전화' })).toBeEnabled();
    expect(within(f).getByText('문자·카카오톡은 휴대전화 번호로만 보낼 수 있습니다.')).toBeVisible();
  });

  test('server 422 messages go under the field without echoing the value', async () => {
    mockWrite(422, { code: 'invalid_phone', message: '전화번호 형식이 맞지 않습니다.', detail: null });
    await openEdit('박현장');
    await userEvent.click(within(form()).getByRole('button', { name: '번호 바꾸기' }));
    await userEvent.type(within(form()).getByLabelText('전화번호'), '010-12-34');
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    const msg = await within(form()).findByText('전화번호 형식이 맞지 않습니다.');
    expect(msg.closest('.ct-field')).toContainElement(within(form()).getByLabelText('전화번호'));
    expect(screen.queryAllByText(/010-12-34/)).toHaveLength(0);
    mockWrite(422, { code: 'invalid_text', message: '메모·까닭에는 보이지 않는 제어 글자나 글 방향을 바꾸는 글자를 쓸 수 없습니다.', detail: { field: 'note' } });
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    const note = await within(form()).findByText(/메모·까닭에는/);
    expect(note.closest('.ct-field')).toContainElement(within(form()).getByLabelText('메모'));
    mockWrite(422, { code: 'something_new', message: '새로운 검사 글입니다.', detail: null });
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    expect(await within(form()).findByText('새로운 검사 글입니다.')).toBeVisible();
  });

  test('channel_not_possible goes under the channel boxes', async () => {
    mockWrite(422, { code: 'channel_not_possible', message: '이 번호로는 전화를 걸 수 없습니다.', detail: null });
    await openEdit('박현장');
    await userEvent.click(within(form()).getByRole('checkbox', { name: '전화' }));
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    const msg = await within(form()).findByText('이 번호로는 전화를 걸 수 없습니다.');
    expect(msg.closest('fieldset')).toHaveAccessibleName('받을 수 있는 것');
    expect(lastWrite()?.body).toEqual({ can_call: false });
  });
});

describe('do-not-contact', () => {
  test('a non-admin clearing it sees the admin-only message', async () => {
    cleanup();
    stubContacts('user');
    mockWrite(403, { code: 'admin_only', message: '수신 거부는 관리자만 풀 수 있습니다(이 번호가 있는 모든 프로젝트에서 풀립니다).', detail: null });
    await openEdit('정배선');
    await userEvent.click(within(form()).getByRole('checkbox', { name: '수신 거부' }));
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    expect(await within(form()).findByText(/수신 거부는 관리자만 풀 수 있습니다/)).toBeVisible();
    expect(lastWrite()?.body).toEqual({ do_not_contact: false });
  });

  test('an admin clearing it confirms that every project with this number is unblocked', async () => {
    await openEdit('정배선');
    await userEvent.click(within(form()).getByRole('checkbox', { name: '수신 거부' }));
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    const ask = await screen.findByRole('alertdialog', { name: '수신 거부 풀기' });
    expect(ask).toHaveTextContent('이 번호가 있는 모든 프로젝트에서 수신 거부가 풀립니다');
    expect(writes()).toHaveLength(0);
    await userEvent.click(within(ask).getByRole('button', { name: '수신 거부 풀기' }));
    await waitFor(() => expect(lastWrite()?.body).toEqual({ do_not_contact: false }));
  });

  test('anyone can turn it on', async () => {
    cleanup();
    stubContacts('user');
    await openEdit('박현장');
    await userEvent.click(within(form()).getByRole('checkbox', { name: '수신 거부' }));
    await userEvent.type(within(form()).getByLabelText('까닭'), '본인 요청');
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(lastWrite()?.body).toEqual({ do_not_contact: true, dnc_reason: '본인 요청' }));
  });

  test('the number field of a do-not-contact person says the old number stays blocked', async () => {
    await openEdit('정배선');
    expect(within(form()).getByText(/번호를 바꿔도 옛 번호는 계속 막힙니다/)).toBeVisible();
    cleanup();
    stubContacts();
    await openEdit('박현장');
    expect(within(form()).queryByText(/번호를 바꿔도 옛 번호는 계속 막힙니다/)).toBeNull();
  });

  async function changeJungNumber(to: string) {
    await openEdit('정배선');
    await userEvent.click(within(form()).getByRole('button', { name: '번호 바꾸기' }));
    if (to) await userEvent.type(within(form()).getByLabelText('전화번호'), to);
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    return screen.findByRole('alertdialog', { name: '새 번호와 수신 거부' });
  }

  test('changing the number asks: keep the new number blocked too', async () => {
    const ask = await changeJungNumber('010-0000-0003');
    expect(ask).toHaveTextContent('예전 번호는 계속 수신 거부로 남습니다. 새 번호도 수신 거부로 둘까요?');
    expect(writes()).toHaveLength(0);
    await userEvent.click(within(ask).getByRole('button', { name: '새 번호도 수신 거부' }));
    await waitFor(() => expect(lastWrite()?.body).toEqual({ phone: '010-0000-0003', do_not_contact: true }));
  });

  test('changing the number asks: the new number can be contacted', async () => {
    const ask = await changeJungNumber('010-0000-0003');
    await userEvent.click(within(ask).getByRole('button', { name: '새 번호는 연락 가능' }));
    await waitFor(() => expect(lastWrite()?.body).toEqual({ phone: '010-0000-0003' }));
  });

  test('removing the number asks too, and cancel sends nothing', async () => {
    const ask = await changeJungNumber('');
    await userEvent.click(within(ask).getByRole('button', { name: '취소' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(writes()).toHaveLength(0);
    await userEvent.click(within(form()).getByRole('button', { name: '저장' }));
    const again = await screen.findByRole('alertdialog', { name: '새 번호와 수신 거부' });
    await userEvent.click(within(again).getByRole('button', { name: '새 번호도 수신 거부' }));
    await waitFor(() => expect(lastWrite()?.body).toEqual({ phone: null, do_not_contact: true }));
  });

  test('the response decides the shown state after a number change', async () => {
    mockWrite(200, detail({ ...JUNG, do_not_contact: false, phone_masked: '010-****-0003' }));
    const ask = await changeJungNumber('010-0000-0003');
    await userEvent.click(within(ask).getByRole('button', { name: '새 번호는 연락 가능' }));
    await waitFor(() => expect(screen.queryByRole('form')).toBeNull());
    expect(contactCalls().filter((c) => c.method === 'GET' && c.url.startsWith('/api/schedules/1/contacts')).length).toBeGreaterThan(1);
  });
});

describe('field manager', () => {
  test('a field manager gets a refusal and no address-book request', async () => {
    cleanup();
    stubContacts('field');
    show();
    expect(await screen.findByText('현장 관리자는 연락처를 열 수 없습니다.')).toBeVisible();
    expect(contactCalls().filter((c) => c.url.startsWith('/api/schedules'))).toHaveLength(0);
  });
});

test('without a schedule the window asks to pick one', async () => {
  useCurrentSchedule.setState({ current: null });
  show();
  expect(await screen.findByText('메뉴바에서 일정을 고르세요.')).toBeVisible();
  expect(BOOK.companies).toHaveLength(3);
  expect(PARK.phone_masked).toBe('010-****-0000');
});
