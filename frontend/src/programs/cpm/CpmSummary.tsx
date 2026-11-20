// CPM 요약 줄 넷: Plan 준수율 · 크리티컬 경로 총 변동 · 만회 계획 달성률 · 프로젝트 완료 편차. 일정 버전이 바뀌면 다시 읽는다.
import { useEffect, useState } from 'react';
import { md } from './cards';
import { getCpmBlock, getRecovery, type CpmBlock, type Recovery } from './cpmApi';

type Loaded<T> = { state: 'loading' } | { state: 'error'; message: string } | { state: 'ok'; value: T };
type Tone = 'danger' | 'success' | 'warning' | 'plain';
interface Stat {
  label: string;
  value: string;
  note: string;
  tone: Tone;
  title?: string;
}

/** 버전마다 한 번 읽는다. 늦게 온 앞 버전의 답은 버린다. */
function useLoaded<T>(load: (id: number) => Promise<T>, id: number, version: number): Loaded<T> {
  const [out, setOut] = useState<{ key: string; data: Loaded<T> }>({ key: '', data: { state: 'loading' } });
  const key = `${id}:${version}`;
  useEffect(() => {
    let live = true;
    load(id).then(
      (value) => live && setOut({ key, data: { state: 'ok', value } }),
      (e: unknown) => live && setOut({ key, data: { state: 'error', message: e instanceof Error ? e.message : String(e) } }),
    );
    return () => {
      live = false;
    };
  }, [load, id, key]);
  return out.key === key || out.data.state === 'ok' ? out.data : { state: 'loading' };
}

/** +4일 · −2일 · 0일 과 그 색(늦음 빨강, 앞섬 초록). */
const signed = (days: number): [string, Tone] =>
  days > 0 ? [`+${days}일`, 'danger'] : days < 0 ? [`−${-days}일`, 'success'] : ['0일', 'plain'];

function pending<T>(label: string, x: Loaded<T>): Stat | null {
  if (x.state === 'loading') return { label, value: '…', note: '읽는 중', tone: 'plain' };
  if (x.state === 'error') return { label, value: '—', note: '읽지 못했습니다', tone: 'plain', title: x.message };
  return null;
}

function cpmStats(x: Loaded<CpmBlock>): Stat[] {
  const labels = ['Plan 준수율', '크리티컬 경로 총 변동', '프로젝트 완료 편차'];
  if (x.state !== 'ok') return labels.map((l) => pending(l, x)!);
  const { plan_compliance: pc, critical_variance: cv, finish_variance: fv } = x.value;
  const compliance: Stat = pc
    ? { label: labels[0], value: `${pc.pct}%`, note: `${pc.done}/${pc.due} 액티비티`, tone: pc.pct < 100 ? 'danger' : 'success' }
    : { label: labels[0], value: '—', note: '기한 지난 Plan 작업 없음', tone: 'plain' };
  const variance: Stat = cv
    ? { label: labels[1], value: signed(cv.days)[0], note: `최대 ${cv.max_id}`, tone: signed(cv.days)[1] }
    : { label: labels[1], value: '—', note: 'Plan 있는 크리티컬 작업 없음', tone: 'plain' };
  const finish: Stat = fv
    ? { label: labels[2], value: signed(fv.days)[0], note: `Plan ${md(fv.plan)} → ${md(fv.current)}`, tone: signed(fv.days)[1] }
    : { label: labels[2], value: '—', note: 'Plan 준공 없음', tone: 'plain' };
  return [compliance, variance, finish];
}

function recoveryStat(x: Loaded<Recovery | null>): Stat {
  const label = '만회 계획 달성률';
  const wait = pending(label, x);
  if (wait || x.state !== 'ok') return wait!;
  const r = x.value;
  if (!r) return { label, value: '—', note: '만회 계획 없음', tone: 'plain' };
  if (r.planned_gain === null) return { label, value: '—', note: '목표 단축 없음', tone: 'plain' };
  if (r.achieved === null) return { label, value: '—', note: '지금 일정을 계산할 수 없습니다', tone: 'plain' };
  if (r.planned_gain <= 0) return { label, value: '—', note: `목표 단축 ${r.planned_gain}일`, tone: 'plain' };
  const pct = Math.round((r.achieved / r.planned_gain) * 100);
  return { label, value: `${pct}%`, note: `${r.achieved}/${r.planned_gain}일 만회`, tone: pct >= 100 ? 'success' : 'warning' };
}

export default function CpmSummary({ scheduleId, version }: { scheduleId: number; version: number }) {
  const cpm = useLoaded(getCpmBlock, scheduleId, version);
  const recovery = useLoaded(getRecovery, scheduleId, version);
  const [compliance, variance, finish] = cpmStats(cpm);
  return (
    <div role="group" aria-label="CPM 요약" className="cpm-summary">
      {[compliance, variance, recoveryStat(recovery), finish].map((s) => (
        <div key={s.label} className="cpm-stat" title={s.title}>
          <span className="cpm-stat-label">{s.label}</span>
          <b className={`cpm-stat-value is-${s.tone}`}>{s.value}</b>
          <span className="cpm-stat-note">{s.note}</span>
        </div>
      ))}
    </div>
  );
}
