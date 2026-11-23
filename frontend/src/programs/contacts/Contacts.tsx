// 「연락처」 창(Task 75, 시안 ①②⑤). 머리 띠(시험 모드 · 허용 번호 n개) · 왼쪽 주소록(협력사별) · 오른쪽 고른 사람의 머리와 대화 자리(ThreadSlot).
// 사람·협력사 양식은 오른쪽 칸을 잠깐 차지한다. 주소록은 프로젝트(일정)마다 따로이고 현장 관리자는 열 수 없다.
// params: id(일정) · contact(고를 사람) · tab('messages' | 'calls') · compose · activity · call(대화 칸에 그대로 넘김).
import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react';
import { useCurrentSchedule } from '../../os/currentSchedule';
import type { ProgramProps } from '../../os/registry';
import { useSession } from '../../os/session';
import { useUiContext } from '../../os/uiContext';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import Tabs from '../../shared/ui/Tabs';
import AddressBook from './AddressBook';
import CompanyForm from './CompanyForm';
import CopyFromProject from './CopyFromProject';
import CsvImport from './CsvImport';
import { getBook, getNotifyStatus, KIND_LABEL, type AddressBook as Book, type Company, type NotifyStatus, type PersonBrief } from './contactsApi';
import PersonForm from './PersonForm';
import ThreadPane from './ThreadPane';
import './contacts.css';

const NAME = '연락처';
const positiveInt = (s: string | undefined) => (s && /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : null);

export type ThreadTab = 'messages' | 'calls';

/** 오른쪽 대화 칸이 받는 값(Task 78 의 ThreadPane 이 이 꼴로 들어온다). */
export interface ThreadSlotProps {
  scheduleId: number;
  person: PersonBrief;
  tab: ThreadTab;
  /** 다른 프로그램이 넘긴 값 — 입력창 미리 채움(compose·activity), 열 통화(call). */
  compose?: string;
  activity?: string;
  call?: string;
  /** 대화가 읽음 수·마지막 줄을 바꿨을 때 주소록을 다시 읽게 한다. */
  onChanged: () => void;
}

/** 대화 칸 자리 — 문자·카카오톡 대화와 통화 탭(Task 78 ThreadPane). */
const ThreadSlot: ComponentType<ThreadSlotProps> = ThreadPane;

type Mode = { kind: 'none' } | { kind: 'person'; id: number | null; companyId: number | null } | { kind: 'company'; company: Company | null };

function StatusStrip({ status, projectName }: { status: NotifyStatus | null | undefined; projectName: string | null }) {
  const badge =
    status === undefined ? null : status && status.ready && status.test_mode ? (
      <span className="ct-badge is-warn">{`시험 모드 · 허용 번호 ${status.allow_count}개`}</span>
    ) : status && status.ready ? null : (
      <span className="ct-badge">알림 연결 설정 전</span>
    );
  return (
    <div className="ct-strip" role="status" aria-label="알림 연결 상태">
      <span className="ct-strip-title ct-ellipsis">{projectName ? `${projectName}의 주소록` : '이 프로젝트의 주소록'}</span>
      {badge}
    </div>
  );
}

function channelText(p: PersonBrief, kakaoReady: boolean): string {
  // channels 는 번호 종류만 보고 정해진다 — 수신 거부가 먼저다.
  if (p.do_not_contact) return '연락할 수 없음(수신 거부)';
  const names = p.channels.filter((c) => c !== 'kakao' || kakaoReady).map((c) => ({ sms: '문자', kakao: '카카오톡', call: '전화' })[c]);
  return names.length ? `${names.join('·')} 가능` : '연락할 수 없음';
}

function PersonHead({ p, company, kakaoReady, tab, onTab, onEdit, onBack }: {
  p: PersonBrief;
  company: string;
  kakaoReady: boolean;
  tab: ThreadTab;
  onTab: (t: ThreadTab) => void;
  onEdit: () => void;
  onBack: () => void;
}) {
  return (
    <div className="ct-head">
      <button type="button" className="ct-back" onClick={onBack}>
        ‹ 목록
      </button>
      <div className="ct-head-main">
        <div className="ct-head-line">
          <h2 className="ct-head-name ct-ellipsis" title={p.name}>{p.name}</h2>
          <span className="ct-head-sub ct-ellipsis" title={[p.role_title, company].filter(Boolean).join(' · ')}>{[p.role_title, company].filter(Boolean).join(' · ')}</span>
        </div>
        <div className="ct-head-line ct-head-sub">
          <span className="ct-num">{p.phone_masked}</span>
          {p.phone_kind && <span className="ct-tag">{KIND_LABEL[p.phone_kind]}</span>}
          {p.do_not_contact && <span className="ct-tag is-bad">수신 거부</span>}
          {p.phone_invalid && <span className="ct-tag is-bad">번호 오류</span>}
          <span className="ct-ellipsis" title={channelText(p, kakaoReady)}>{channelText(p, kakaoReady)}</span>
        </div>
      </div>
      <div className="ct-head-acts">
        <Tabs
          label="대화 종류"
          value={tab}
          onChange={(t) => onTab(t as ThreadTab)}
          items={[
            { id: 'messages', label: '문자 · 카카오톡' },
            { id: 'calls', label: '통화' },
          ]}
        />
        <Button onClick={onEdit}>고치기</Button>
      </div>
    </div>
  );
}

function useBook(scheduleId: number, showHidden: boolean) {
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    getBook(scheduleId, showHidden).then(
      (b) => {
        if (!live) return;
        setBook(b);
        setError(null);
      },
      (e: unknown) => live && setError(e instanceof Error ? e.message : '주소록을 읽을 수 없습니다.'),
    );
    return () => {
      live = false;
    };
  }, [scheduleId, showHidden, n]);
  const reload = useCallback(() => setN((x) => x + 1), []);
  return { book, error, reload };
}

function useNotifyStatus() {
  const [status, setStatus] = useState<NotifyStatus | null | undefined>(undefined);
  useEffect(() => {
    let live = true;
    void getNotifyStatus().then((s) => live && setStatus(s));
    return () => {
      live = false;
    };
  }, []);
  return status;
}

type Params = Record<string, string> | undefined;

interface PaneProps {
  mode: Mode;
  setMode: (m: Mode) => void;
  scheduleId: number;
  book: Book | null;
  selected: PersonBrief | null;
  setSelectedId: (id: number | null) => void;
  projectName: string | null;
  isAdmin: boolean;
  kakaoReady: boolean;
  tab: ThreadTab;
  setTab: (t: ThreadTab) => void;
  params: Params;
  reload: () => void;
}

/** 오른쪽 칸: 사람·협력사 양식, 또는 고른 사람의 머리 + 대화 자리, 또는 고르라는 글. */
function Pane({ mode, setMode, scheduleId, book, selected, setSelectedId, projectName, isAdmin, kakaoReady, tab, setTab, params, reload }: PaneProps) {
  const close = () => setMode({ kind: 'none' });
  // 넘겨받은 글·작업(params.compose·activity)은 params.contact 인 사람의 입력창에만, 한 번만 — 그 입력창이 처음 그려진 뒤에는
  // 다시 넘기지 않는다(다른 사람에게 가거나, 보낸 뒤 돌아와도 다시 채워지지 않게). 같은 내용을 다시 넘겨받아도 다시 채우지 않는다.
  const handKey = `${params?.contact ?? ''}\u0000${params?.compose ?? ''}\u0000${params?.activity ?? ''}`;
  const [usedKey, setUsedKey] = useState<string | null>(null);
  const handing = mode.kind === 'none' && selected !== null && selected.id === positiveInt(params?.contact) && usedKey !== handKey;
  useEffect(() => {
    if (handing && tab === 'messages') setUsedKey(handKey);
  }, [handing, tab, handKey]);
  if (mode.kind === 'person')
    return (
      <PersonForm
        key={`p${mode.id ?? 'new'}`}
        scheduleId={scheduleId}
        personId={mode.id}
        companyId={mode.companyId}
        companies={book?.companies ?? []}
        projectName={projectName}
        isAdmin={isAdmin}
        kakaoReady={kakaoReady}
        onCancel={close}
        onSaved={(p) => {
          setSelectedId(p.id);
          close();
          reload();
        }}
      />
    );
  if (mode.kind === 'company')
    return (
      <CompanyForm
        key={`c${mode.company?.id ?? 'new'}`}
        scheduleId={scheduleId}
        company={mode.company}
        onCancel={close}
        onSaved={() => {
          close();
          reload();
        }}
      />
    );
  if (!selected)
    return <p className="ct-muted ct-pad ct-pick">{book && book.companies.length === 0 ? '협력사를 추가하면 사람을 넣을 수 있습니다.' : '왼쪽 주소록에서 사람을 고르세요.'}</p>;
  const company = book?.companies.find((c) => c.id === selected.company_id)?.name ?? '';
  return (
    <>
      <PersonHead
        p={selected}
        company={company}
        kakaoReady={kakaoReady}
        tab={tab}
        onTab={setTab}
        onEdit={() => setMode({ kind: 'person', id: selected.id, companyId: null })}
        onBack={() => setSelectedId(null)}
      />
      <section className="ct-slot" aria-label="대화" data-tab={tab}>
        <ThreadSlot key={selected.id} scheduleId={scheduleId} person={selected} tab={tab} compose={handing ? params?.compose : undefined} activity={handing ? params?.activity : undefined} call={params?.call} onChanged={reload} />
      </section>
    </>
  );
}

/** 같은 창을 다른 params 로 다시 열면(다른 프로그램의 open('contacts', {...})) 그 사람·탭으로. */
function useParamSelection(params: Params, setMode: (m: Mode) => void) {
  const [selectedId, setSelectedId] = useState<number | null>(() => positiveInt(params?.contact));
  const [tab, setTab] = useState<ThreadTab>(params?.tab === 'calls' ? 'calls' : 'messages');
  const seen = useRef(params);
  useEffect(() => {
    if (seen.current === params) return;
    seen.current = params;
    const id = positiveInt(params?.contact);
    if (id !== null) {
      setSelectedId(id);
      setMode({ kind: 'none' });
    }
    if (params?.tab === 'calls' || params?.tab === 'messages') setTab(params.tab);
  }, [params, setMode]);
  return { selectedId, setSelectedId, tab, setTab };
}

function ContactsBody({ windowId, scheduleId, params, projectName }: { windowId: string; scheduleId: number; params: Params; projectName: string | null }) {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const [showHidden, setShowHidden] = useState(false);
  const { book, error, reload } = useBook(scheduleId, showHidden);
  const status = useNotifyStatus();
  const [mode, setMode] = useState<Mode>({ kind: 'none' });
  const [xfer, setXfer] = useState<'import' | 'copy' | null>(null); // 이 몸은 일정마다 새로 그려진다 → 프로젝트를 바꾸면 대화상자도 닫힌다
  const { selectedId, setSelectedId, tab, setTab } = useParamSelection(params, setMode);

  useEffect(() => {
    useWindows.getState().setTitle(windowId, projectName ? `${NAME} — ${projectName}` : NAME);
  }, [windowId, projectName]);
  useEffect(() => {
    useUiContext.getState().publish(windowId, { program: 'contacts', schedule_id: scheduleId });
  }, [windowId, scheduleId]);

  const selected = book?.companies.flatMap((c) => c.people).find((p) => p.id === selectedId) ?? null;
  const paneOpen = mode.kind !== 'none' || selected !== null;
  const isAdmin = role === 'admin';

  return (
    <div className={`ct-root${paneOpen ? ' has-pane' : ''}`}>
      <StatusStrip status={status} projectName={projectName} />
      <div className="ct-main">
        <AddressBook
          book={book}
          error={error}
          selectedId={selectedId}
          onSelect={(p) => {
            setSelectedId(p.id);
            setMode({ kind: 'none' });
          }}
          onAddPerson={(companyId) => setMode({ kind: 'person', id: null, companyId })}
          onAddCompany={() => setMode({ kind: 'company', company: null })}
          onEditCompany={(c) => setMode({ kind: 'company', company: c })}
          showHidden={showHidden}
          onShowHidden={setShowHidden}
          isAdmin={isAdmin}
          onImport={() => setXfer('import')}
          onCopy={isAdmin ? () => setXfer('copy') : undefined}
        />
        <section className="ct-pane" aria-label={selected && mode.kind === 'none' ? `${selected.name} 대화` : '연락처 자세히'}>
          {mode.kind !== 'none' && (
            <button type="button" className="ct-back ct-back-form" onClick={() => setMode({ kind: 'none' })}>
              ‹ 목록
            </button>
          )}
          <Pane
            mode={mode}
            setMode={setMode}
            scheduleId={scheduleId}
            book={book}
            selected={selected}
            setSelectedId={setSelectedId}
            projectName={projectName}
            isAdmin={isAdmin}
            kakaoReady={status?.kakao_ready === true}
            tab={tab}
            setTab={setTab}
            params={params}
            reload={reload}
          />
        </section>
      </div>
      {xfer === 'import' && <CsvImport scheduleId={scheduleId} onClose={() => setXfer(null)} onDone={reload} />}
      {xfer === 'copy' && <CopyFromProject scheduleId={scheduleId} onClose={() => setXfer(null)} onDone={reload} />}
    </div>
  );
}

function Notice({ windowId, text }: { windowId: string; text: string }) {
  useEffect(() => {
    useWindows.getState().setTitle(windowId, NAME);
    useUiContext.getState().publish(windowId, { program: 'contacts', schedule_id: null });
  }, [windowId]);
  return (
    <div className="ct-root">
      <p className="ct-muted ct-pad">{text}</p>
    </div>
  );
}

export default function Contacts({ windowId, params }: ProgramProps) {
  const role = useSession((s) => s.session?.user.role);
  const current = useCurrentSchedule((s) => s.current);
  if (role === 'field') return <Notice windowId={windowId} text="현장 관리자는 연락처를 열 수 없습니다." />;
  const scheduleId = positiveInt(params?.id) ?? current?.id ?? null;
  if (scheduleId === null) return <Notice windowId={windowId} text="메뉴바에서 일정을 고르세요." />;
  const projectName = current?.id === scheduleId ? current.name : null;
  return <ContactsBody key={scheduleId} windowId={windowId} scheduleId={scheduleId} params={params} projectName={projectName} />;
}
