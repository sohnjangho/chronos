import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api, ApiError } from '../shared/api';
import Button from '../shared/ui/Button';
import { useCurrentSchedule } from './currentSchedule';
import { useModalFocus } from './modalFocus';
import { useWindows } from './windowStore';
import './newProjectModal.css';

interface CreatedSchedule {
  id: number;
  name: string;
  domain: string;
  level: string;
  version: number;
  finish: string | null;
}

const DOMAIN_OPTIONS = [
  { value: 'general', label: '범용 · 일반 프로젝트' },
  { value: 'rnd', label: 'R&D 연구개발' },
  { value: 'permitting', label: '인허가 · 행정' },
  { value: 'procurement', label: '자재 조달 · 공급' },
  { value: 'software', label: '소프트웨어 · IT' },
  { value: 'marketing', label: '마케팅 · 행사' },
  { value: 'manufacturing', label: '생산 · 제조' },
  { value: 'construction', label: '건설 · 시공' },
  { value: 'custom', label: '직접 입력…' },
];

const LEVELS = ['L1', 'L2', 'L3', 'L4', 'L5'] as const;

function todayIso(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export default function NewProjectModal() {
  const mode = useCurrentSchedule((s) => s.newProjectModal);
  const close = useCurrentSchedule((s) => s.closeNewProjectModal);
  const [tab, setTab] = useState<'direct' | 'ai'>('direct');
  const [name, setName] = useState('');
  const [domainPreset, setDomainPreset] = useState('general');
  const [customDomain, setCustomDomain] = useState('');
  const [level, setLevel] = useState<(typeof LEVELS)[number]>('L3');
  const [start, setStart] = useState(todayIso);
  const [daysPerWeek, setDaysPerWeek] = useState<5 | 6 | 7>(5);
  const [aiTopic, setAiTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const trap = useModalFocus(dialogRef);

  useEffect(() => {
    if (mode !== 'closed') {
      setTab(mode);
      setError(null);
      setBusy(false);
    }
  }, [mode]);

  if (mode === 'closed') return null;

  async function submitDirect(e: FormEvent) {
    e.preventDefault();
    const cleanName = name.trim();
    if (!cleanName) {
      setError('프로젝트 이름을 입력해 주세요.');
      return;
    }
    const domain = domainPreset === 'custom' ? customDomain.trim() || 'general' : domainPreset;
    setBusy(true);
    setError(null);
    try {
      const created = await api<CreatedSchedule>('/api/schedules', {
        method: 'POST',
        body: JSON.stringify({
          name: cleanName,
          domain,
          level,
          start: start || null,
          days_per_week: daysPerWeek,
        }),
      });
      const cs = useCurrentSchedule.getState();
      cs.bumpReload();
      cs.setCurrent({ id: created.id, name: created.name });
      close();
      setName('');
      setCustomDomain('');
      useWindows.getState().open('gantt', { id: String(created.id) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '프로젝트 생성에 실패했습니다.');
    } finally {
      setBusy(false);
    }
  }

  function startAiProject(e: FormEvent) {
    e.preventDefault();
    const topic = aiTopic.trim();
    useCurrentSchedule.getState().enterNewProjectMode();
    useWindows.getState().open('chat');
    setAiTopic('');
    void import('../programs/chat/chatStore').then(({ useChat }) => {
      useChat.getState().newChat(null);
      if (topic) void useChat.getState().send(topic);
    });
  }

  return (
    <div
      className="os-newproj-back"
      onPointerDown={(e) => {
        if (e.target === e.currentTarget && !busy) close();
      }}
    >
      <div
        ref={dialogRef}
        className="os-newproj-modal"
        role="dialog"
        aria-modal="true"
        aria-label="새 프로젝트 만들기"
        tabIndex={-1}
        onKeyDown={(e) => (e.key === 'Escape' && !busy ? close() : trap(e))}
      >
        <div className="os-newproj-head">
          <h2 className="os-newproj-title">새 프로젝트 만들기</h2>
          <button type="button" className="os-newproj-x" aria-label="닫기" onClick={close} disabled={busy}>
            ×
          </button>
        </div>

        <div className="os-newproj-tabs" role="tablist" aria-label="생성 방식">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'direct'}
            className={`os-newproj-tab ${tab === 'direct' ? 'is-active' : ''}`}
            onClick={() => setTab('direct')}
          >
            직접 빈 프로젝트 생성
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'ai'}
            className={`os-newproj-tab ${tab === 'ai' ? 'is-active' : ''}`}
            onClick={() => setTab('ai')}
          >
            AI 에이전트로 일정 생성
          </button>
        </div>

        {tab === 'direct' ? (
          <form className="os-newproj-form" onSubmit={(e) => void submitDirect(e)}>
            <label className="os-newproj-field">
              <span>프로젝트 이름</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="예: 차세대 배터리 R&D 일정, 신규 공장 인허가"
                required
                autoFocus
              />
            </label>

            <div className="os-newproj-grid">
              <label className="os-newproj-field">
                <span>분야</span>
                <select value={domainPreset} onChange={(e) => setDomainPreset(e.target.value)}>
                  {DOMAIN_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="os-newproj-field">
                <span>정밀도</span>
                <select value={level} onChange={(e) => setLevel(e.target.value as (typeof LEVELS)[number])}>
                  {LEVELS.map((lv) => (
                    <option key={lv} value={lv}>
                      {lv}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {domainPreset === 'custom' && (
              <label className="os-newproj-field">
                <span>분야 코드 또는 이름</span>
                <input
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="예: aerospace, 바이오임상, marketing"
                />
              </label>
            )}

            <div className="os-newproj-grid">
              <label className="os-newproj-field">
                <span>시작일</span>
                <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </label>

              <label className="os-newproj-field">
                <span>주 근무일</span>
                <select value={daysPerWeek} onChange={(e) => setDaysPerWeek(Number(e.target.value) as 5 | 6 | 7)}>
                  <option value={5}>주 5일</option>
                  <option value={6}>주 6일</option>
                  <option value={7}>주 7일</option>
                </select>
              </label>
            </div>

            {error && (
              <p className="os-newproj-error" role="alert">
                {error}
              </p>
            )}

            <div className="os-newproj-actions">
              <Button onClick={close} disabled={busy}>
                취소
              </Button>
              <Button type="submit" variant="primary" disabled={busy}>
                {busy ? '생성 중…' : '프로젝트 생성'}
              </Button>
            </div>
          </form>
        ) : (
          <form className="os-newproj-form" onSubmit={startAiProject}>
            <p className="os-newproj-desc">
              기존 일정과 완전히 격리된 상태로 새 대화창을 열고, R&amp;D·인허가·조달·SW·제조·건설 등 어떤 분야든 AI와 함께 새 일정 프로젝트를 만듭니다.
            </p>
            <label className="os-newproj-field">
              <span>만들려는 일정 주제 (선택)</span>
              <input
                type="text"
                value={aiTopic}
                onChange={(e) => setAiTopic(e.target.value)}
                placeholder="비워 두면 새 대화만 엽니다. 예: 해외 설비 조달 일정 짜줘"
                autoFocus
              />
            </label>
            <div className="os-newproj-actions">
              <Button onClick={close}>취소</Button>
              <Button type="submit" variant="primary">
                새 프로젝트 대화 시작
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
