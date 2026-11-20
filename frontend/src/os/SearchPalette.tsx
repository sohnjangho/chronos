import { useEffect, useRef, useState } from 'react';
import { useModalFocus } from './modalFocus';
import { api } from '../shared/api';
import { ageText } from './ApprovalWidget';
import { useCurrentSchedule } from './currentSchedule';
import PickList, { type PickGroup } from './PickList';
import ProgramIcon from './ProgramIcon';
import { programs } from './registry';
import { scheduleText, type ScheduleItem } from './ScheduleSelector';
import { useSession } from './session';
import { useShell } from './shell';
import { useWindows } from './windowStore';
import './overlays.css';

interface Pending {
  id: number;
  title: string;
  created_at: string;
}
interface Activity {
  id: string;
  name: string;
}

const MAX_ACTIVITIES = 30;

/** 검색 대상: 일정 목록·승인 대기·지금 일정의 액티비티. 열 때마다 읽는다(실패한 묶음은 비운다). */
function usePaletteData(scheduleId: number | null) {
  const [schedules, setSchedules] = useState<ScheduleItem[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  useEffect(() => {
    api<ScheduleItem[]>('/api/schedules').then(setSchedules, () => {});
    api<{ items: Pending[] }>('/api/approvals?status=pending').then((r) => setPending(r.items), () => {});
    if (scheduleId !== null)
      api<{ activities: Activity[] }>(`/api/schedules/${scheduleId}`).then((r) => setActivities(r.activities), () => {});
  }, [scheduleId]);
  return { schedules, pending, activities };
}

interface GroupArgs {
  role: 'admin' | 'user';
  query: string;
  currentId: number | undefined;
  data: ReturnType<typeof usePaletteData>;
  done(fn: () => void): () => void;
}

/** 검색 결과 묶음: 프로그램 · 일정 · 승인 대기 · 액티비티(지금 일정, 최대 30). */
function paletteGroups({ role, query, currentId, data, done }: GroupArgs): PickGroup[] {
  const q = query.trim().toLowerCase();
  const match = (text: string) => text.toLowerCase().includes(q);
  const open = useWindows.getState().open;
  return [
    {
      title: '프로그램',
      items: programs(role)
        .filter((p) => match(p.name))
        .map((p) => ({ key: `p-${p.id}`, label: p.name, icon: <ProgramIcon program={p} size={20} />, run: done(() => open(p.id)) })),
    },
    {
      title: '일정',
      items: data.schedules
        .filter((s) => match(scheduleText(s)))
        .map((s) => ({
          key: `s-${s.id}`,
          label: scheduleText(s),
          selected: s.id === currentId,
          run: done(() => useCurrentSchedule.getState().setCurrent({ id: s.id, name: s.name })),
        })),
    },
    {
      title: '승인 대기',
      items: data.pending
        .filter((a) => match(a.title))
        .map((a) => ({ key: `a-${a.id}`, label: a.title, detail: ageText(a.created_at), run: done(() => open('approvals', { id: String(a.id) })) })),
    },
    {
      title: '액티비티',
      items: data.activities
        .filter((a) => match(`${a.id} ${a.name}`))
        .slice(0, MAX_ACTIVITIES)
        .map((a) => ({ key: `x-${a.id}`, label: a.name, detail: a.id, run: done(() => open('schedule-table', { activity: a.id })) })),
    },
  ];
}

function PaletteView() {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const current = useCurrentSchedule((s) => s.current);
  const [query, setQuery] = useState('');
  const data = usePaletteData(current?.id ?? null);
  const close = () => useShell.getState().setPalette(false);
  const done = (fn: () => void) => () => {
    fn();
    close();
  };
  const groups = paletteGroups({ role, query, currentId: current?.id, data, done });
  const ref = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(ref);
  return (
    <div className="os-palette-back" onPointerDown={(e) => e.target === e.currentTarget && close()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label="검색" className="os-palette" onKeyDown={trap}>
        <PickList label="검색어" placeholder="프로그램·일정·승인 대기·액티비티 찾기" query={query} onQuery={setQuery} groups={groups} onClose={close} />
      </div>
    </div>
  );
}

/** 전역 검색(Ctrl+K, 바탕화면에서 /): 프로그램 열기 · 일정 바꾸기 · 승인 열기 · 액티비티로 스케줄 열기. */
export default function SearchPalette() {
  const open = useShell((s) => s.palette);
  return open ? <PaletteView /> : null;
}
