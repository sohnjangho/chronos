// 「보고서」 화면: 월간·분기별 보고서 생성, 프로젝트별 학습 양식 기억, 타 프로젝트 양식 선택·복사, PDF/Word 내보내기.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../shared/api';
import { dot } from '../../shared/schedule/format';
import { useSchedule, useScheduleStore } from '../../shared/schedule/scope';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { ReportChart } from './ReportCharts';
import {
  BINDING_OPTIONS,
  adoptTemplate,
  createTemplate,
  deleteReport,
  deleteTemplate,
  exportReportFile,
  generateReport,
  getReport,
  learnTemplate,
  listReports,
  listTemplates,
  regenerateReport,
  reviseReportBlock,
  updateReport,
  updateTemplate,
  uploadTemplateFile,
  type Cadence,
  type DataBinding,
  type ReportBlock,
  type ReportDetail,
  type ReportSummary,
  type ReportTemplateItem,
  type StyleMemory,
  type TemplateSection,
} from './reportsApi';
import './reports.css';

interface DraftTemplateState {
  mode: 'new' | 'edit' | 'readonly';
  templateId: number | null;
  sourceProjectName: string | null;
  sourceFileId: number | null;
  sourceFileName: string | null;
  name: string;
  cadence: Cadence;
  isDefault: boolean;
  isBuiltin: boolean;
  sections: TemplateSection[];
  style: StyleMemory;
}

function defaultPeriod(dataDate: string | null, cadence: Cadence): string {
  const iso = dataDate ?? new Date().toISOString().slice(0, 10);
  const [yStr, mStr] = iso.split('-');
  const year = Number(yStr) || new Date().getFullYear();
  const month = Number(mStr) || 1;
  if (cadence === 'quarterly') return `${year}년 ${Math.floor((month - 1) / 3) + 1}분기`;
  return `${year}년 ${month}월`;
}

function toDraft(tpl: ReportTemplateItem, currentScheduleId: number): DraftTemplateState {
  const owned = !tpl.is_builtin && tpl.schedule_id === currentScheduleId;
  return {
    mode: owned ? 'edit' : 'readonly',
    templateId: tpl.id,
    sourceProjectName: tpl.project_name,
    sourceFileId: tpl.source_file_id,
    sourceFileName: tpl.source_file_name,
    name: tpl.name,
    cadence: tpl.cadence,
    isDefault: tpl.is_default,
    isBuiltin: tpl.is_builtin,
    sections: tpl.sections.map((s) => ({ ...s, table_columns: [...s.table_columns] })),
    style: { ...tpl.style, learned_rules: [...tpl.style.learned_rules] },
  };
}

function bindingKindOf(binding: DataBinding) {
  return BINDING_OPTIONS.find((b) => b.value === binding)?.kind ?? 'manual';
}

const CADENCE_TEXT: Record<Cadence, string> = { monthly: '월간', quarterly: '분기' };

export default function ReportsTab() {
  const scheduleId = useScheduleStore().getState().scheduleId;
  const projectName = useSchedule((s) => s.view?.name ?? '');
  const dataDate = useSchedule((s) => s.view?.data_date ?? null);

  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [templates, setTemplates] = useState<{ current_project: ReportTemplateItem[]; other_projects: ReportTemplateItem[]; builtins: ReportTemplateItem[] }>({
    current_project: [],
    other_projects: [],
    builtins: [],
  });
  const [cadenceFilter, setCadenceFilter] = useState<'all' | Cadence>('all');
  const [activeReport, setActiveReport] = useState<ReportDetail | null>(null);
  const [draftTitle, setDraftTitle] = useState('');
  const [draftBlocks, setDraftBlocks] = useState<ReportBlock[]>([]);

  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [inspectorTab, setInspectorTab] = useState<'sections' | 'style'>('sections');
  const [inspected, setInspected] = useState<DraftTemplateState | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createCadence, setCreateCadence] = useState<Cadence>('monthly');
  const [createPeriod, setCreatePeriod] = useState('');
  const [createTplChoice, setCreateTplChoice] = useState('');
  const [createExtra, setCreateExtra] = useState('');

  const [learnOpen, setLearnOpen] = useState(false);
  const [learnFile, setLearnFile] = useState<File | null>(null);
  const [learnCadence, setLearnCadence] = useState<Cadence>('monthly');
  const [learnName, setLearnName] = useState('');

  const [reviseTarget, setReviseTarget] = useState<string | null>(null);
  const [reviseInstruction, setReviseInstruction] = useState('');
  const [reviseRemember, setReviseRemember] = useState(true);
  const [newRuleText, setNewRuleText] = useState('');

  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const syncReportDraft = (rep: ReportDetail | null) => {
    setActiveReport(rep);
    setDraftTitle(rep?.title ?? '');
    setDraftBlocks(rep ? rep.blocks.map((b) => ({ ...b })) : []);
    setReviseTarget(null);
    setReviseInstruction('');
  };

  const refresh = useCallback(
    async (selectReportId?: number | null) => {
      try {
        const [repRes, tplRes] = await Promise.all([listReports(scheduleId), listTemplates(scheduleId)]);
        setTemplates(tplRes);
        setReports(repRes.items);
        setError(null);

        const targetId = selectReportId !== undefined ? selectReportId : repRes.items[0]?.id;
        if (targetId) {
          const detail = await getReport(scheduleId, targetId);
          syncReportDraft(detail);
          const allTpls = [...tplRes.current_project, ...tplRes.other_projects, ...tplRes.builtins];
          const matched =
            detail.template_id !== null
              ? allTpls.find((t) => t.id === detail.template_id)
              : tplRes.builtins.find((t) => t.cadence === detail.cadence);
          if (matched) setInspected((prev) => (prev?.mode === 'new' ? prev : toDraft(matched, scheduleId)));
        } else {
          syncReportDraft(null);
          const fallback = tplRes.current_project[0] ?? tplRes.builtins[0];
          if (fallback) setInspected((prev) => (prev?.mode === 'new' ? prev : toDraft(fallback, scheduleId)));
        }
      } catch (e: unknown) {
        setError(e instanceof ApiError ? e.message : '보고서 목록을 읽을 수 없습니다.');
      }
    },
    [scheduleId],
  );

  useEffect(() => {
    setInspected(null);
    setCreateOpen(false);
    setLearnOpen(false);
    setNotice(null);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setCreatePeriod(defaultPeriod(dataDate, createCadence));
  }, [dataDate, createCadence]);

  const filteredReports = useMemo(
    () => (cadenceFilter === 'all' ? reports : reports.filter((r) => r.cadence === cadenceFilter)),
    [reports, cadenceFilter],
  );

  const filterTpls = (list: ReportTemplateItem[]) =>
    cadenceFilter === 'all' ? list : list.filter((t) => t.cadence === cadenceFilter);

  const openReport = async (id: number) => {
    setBusy('open');
    setError(null);
    try {
      const detail = await getReport(scheduleId, id);
      syncReportDraft(detail);
      const allTpls = [...templates.current_project, ...templates.other_projects, ...templates.builtins];
      const matched =
        detail.template_id !== null
          ? allTpls.find((t) => t.id === detail.template_id)
          : templates.builtins.find((t) => t.cadence === detail.cadence);
      if (matched) setInspected(toDraft(matched, scheduleId));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서를 열 수 없습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleGenerate = async (cadenceOverride?: Cadence) => {
    const cad = cadenceOverride ?? createCadence;
    setBusy('generate');
    setError(null);
    setNotice(null);
    try {
      let tplId: number | null = null;
      let useBuiltin = false;
      if (!cadenceOverride && createTplChoice) {
        if (createTplChoice === 'builtin') useBuiltin = true;
        else if (createTplChoice.startsWith('id:')) tplId = Number(createTplChoice.slice(3));
      }
      const created = await generateReport(scheduleId, {
        cadence: cad,
        template_id: tplId,
        use_builtin: useBuiltin,
        period_label: cadenceOverride ? defaultPeriod(dataDate, cad) : createPeriod.trim() || undefined,
        extra_note: cadenceOverride ? '' : createExtra.trim(),
      });
      setCreateOpen(false);
      setCreateExtra('');
      setNotice(`「${created.title}」 보고서를 작성했습니다.`);
      await refresh(created.id);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleLearnFile = async () => {
    if (!learnFile) return;
    setBusy('learn');
    setError(null);
    setNotice(null);
    try {
      const uploaded = await uploadTemplateFile(learnFile);
      const learned = await learnTemplate({
        file_id: uploaded.file_id,
        schedule_id: scheduleId,
        cadence: learnCadence,
        name: learnName.trim() || undefined,
      });
      setInspected({
        mode: 'new',
        templateId: null,
        sourceProjectName: projectName || null,
        sourceFileId: learned.source_file_id,
        sourceFileName: learned.source_file_name,
        name: learned.suggested_name,
        cadence: learned.suggested_cadence,
        isDefault: true,
        isBuiltin: false,
        sections: learned.sections,
        style: learned.style,
      });
      setInspectorOpen(true);
      setInspectorTab('sections');
      setLearnOpen(false);
      setLearnFile(null);
      setLearnName('');
      setNotice(`${learned.analysis_summary} 오른쪽 패널에서 매핑과 말투를 확인한 뒤 저장하세요.`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식 파일을 분석하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleSaveTemplate = async () => {
    if (!inspected) return;
    setBusy('save-tpl');
    setError(null);
    try {
      let saved: ReportTemplateItem;
      if (inspected.mode === 'new') {
        saved = await createTemplate({
          schedule_id: scheduleId,
          cadence: inspected.cadence,
          name: inspected.name.trim() || '새 보고서 양식',
          is_default: inspected.isDefault,
          source_file_id: inspected.sourceFileId,
          source_file_name: inspected.sourceFileName,
          sections: inspected.sections,
          style: inspected.style,
        });
        setNotice(`「${saved.name}」 양식을 현재 프로젝트에 기억했습니다.`);
      } else if (inspected.mode === 'edit' && inspected.templateId !== null) {
        saved = await updateTemplate(inspected.templateId, {
          name: inspected.name.trim() || '보고서 양식',
          cadence: inspected.cadence,
          is_default: inspected.isDefault,
          sections: inspected.sections,
          style: inspected.style,
        });
        setNotice(`「${saved.name}」 양식 설정을 저장했습니다.`);
      } else {
        return;
      }
      const tplRes = await listTemplates(scheduleId);
      setTemplates(tplRes);
      setInspected(toDraft(saved, scheduleId));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식을 저장하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleAdoptTemplate = async () => {
    if (!inspected || inspected.templateId === null) return;
    setBusy('adopt');
    setError(null);
    try {
      const cloned = await adoptTemplate(inspected.templateId, { schedule_id: scheduleId, is_default: true });
      const tplRes = await listTemplates(scheduleId);
      setTemplates(tplRes);
      setInspected(toDraft(cloned, scheduleId));
      setNotice(`「${cloned.name}」 양식을 현재 프로젝트 양식으로 복사·기억했습니다.`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식을 복사하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleDeleteTemplate = async (id: number) => {
    setBusy('del-tpl');
    setError(null);
    try {
      await deleteTemplate(id);
      const tplRes = await listTemplates(scheduleId);
      setTemplates(tplRes);
      if (inspected?.templateId === id) {
        const fb = tplRes.current_project[0] ?? tplRes.builtins[0];
        setInspected(fb ? toDraft(fb, scheduleId) : null);
      }
      setNotice('학습된 양식을 삭제했습니다.');
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식을 삭제하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleSaveReportContent = async () => {
    if (!activeReport) return;
    setBusy('save-rep');
    setError(null);
    try {
      const saved = await updateReport(scheduleId, activeReport.id, {
        title: draftTitle.trim() || activeReport.title,
        blocks: draftBlocks,
      });
      syncReportDraft(saved);
      setReports((prev) => prev.map((r) => (r.id === saved.id ? { ...r, title: saved.title, updated_at: saved.updated_at } : r)));
      setNotice('보고서 수정 내용을 저장했습니다.');
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서를 저장하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleRegenerate = async () => {
    if (!activeReport) return;
    setBusy('regen');
    setError(null);
    try {
      const updated = await regenerateReport(scheduleId, activeReport.id, {});
      syncReportDraft(updated);
      setNotice(`일정 v${updated.schedule_version} 기준으로 보고서를 다시 작성했습니다.`);
      await refresh(updated.id);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서를 다시 작성하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleReviseBlock = async (blockId: string) => {
    if (!activeReport || !reviseInstruction.trim()) return;
    setBusy('revise');
    setError(null);
    try {
      const updated = await reviseReportBlock(scheduleId, activeReport.id, {
        block_id: blockId,
        instruction: reviseInstruction.trim(),
        remember_rule: reviseRemember,
      });
      syncReportDraft(updated);
      setReviseTarget(null);
      setReviseInstruction('');
      if (reviseRemember) {
        const tplRes = await listTemplates(scheduleId);
        setTemplates(tplRes);
        const matched = updated.template_id ? tplRes.current_project.find((t) => t.id === updated.template_id) : undefined;
        if (matched) setInspected(toDraft(matched, scheduleId));
      }
      setNotice(reviseRemember ? '항목을 수정하고 프로젝트 양식 규칙에 기억했습니다.' : '항목을 수정했습니다.');
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '항목 수정을 처리하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const updateSection = (idx: number, patch: Partial<TemplateSection>) => {
    if (!inspected) return;
    setInspected({
      ...inspected,
      sections: inspected.sections.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
    });
  };

  const moveSection = (idx: number, delta: -1 | 1) => {
    if (!inspected) return;
    const to = idx + delta;
    if (to < 0 || to >= inspected.sections.length) return;
    const next = [...inspected.sections];
    const [moved] = next.splice(idx, 1);
    next.splice(to, 0, moved);
    setInspected({ ...inspected, sections: next });
  };

  const addSection = () => {
    if (!inspected) return;
    const nextNum = inspected.sections.length + 1;
    setInspected({
      ...inspected,
      sections: [
        ...inspected.sections,
        {
          id: `s${Date.now()}`,
          heading: `${nextNum}. 추가 항목`,
          block_kind: 'manual',
          data_binding: 'manual_input',
          table_columns: [],
          section_prompt: '',
        },
      ],
    });
  };

  const removeSection = (idx: number) => {
    if (!inspected || inspected.sections.length <= 1) return;
    setInspected({ ...inspected, sections: inspected.sections.filter((_, i) => i !== idx) });
  };

  const readOnlyTpl = inspected?.mode === 'readonly';

  return (
    <div className="rp-root">
      <aside className="rp-sidebar" aria-label="보고서와 양식 목록">
        <div className="rp-side-actions">
          <Button variant="primary" onClick={() => setCreateOpen((v) => !v)} disabled={busy !== null}>
            + 보고서 만들기
          </Button>
          <div className="rp-seg" role="group" aria-label="보고 주기 필터">
            {(['all', 'monthly', 'quarterly'] as const).map((c) => (
              <button key={c} type="button" aria-pressed={cadenceFilter === c} onClick={() => setCadenceFilter(c)}>
                {c === 'all' ? '전체' : c === 'monthly' ? '월간' : '분기'}
              </button>
            ))}
          </div>
        </div>

        {createOpen && (
          <div className="rp-form-box" role="region" aria-label="새 보고서 설정">
            <div className="rp-seg" role="group" aria-label="보고 주기 선택">
              {(['monthly', 'quarterly'] as const).map((c) => (
                <button key={c} type="button" aria-pressed={createCadence === c} onClick={() => setCreateCadence(c)}>
                  {c === 'monthly' ? '월간 보고서' : '분기별 보고서'}
                </button>
              ))}
            </div>
            <label className="rp-field">
              <span>보고 기간</span>
              <input value={createPeriod} onChange={(e) => setCreatePeriod(e.target.value)} placeholder="예: 2027년 6월" />
            </label>
            <label className="rp-field">
              <span>적용할 양식</span>
              <select aria-label="적용할 양식" value={createTplChoice} onChange={(e) => setCreateTplChoice(e.target.value)}>
                <option value="">자동 (현재 프로젝트 기본 양식 우선)</option>
                {templates.current_project.length > 0 && (
                  <optgroup label="현재 프로젝트 양식">
                    {templates.current_project.map((t) => (
                      <option key={`c-${t.id}`} value={`id:${t.id}`}>
                        {`${t.name} [${CADENCE_TEXT[t.cadence]}]${t.is_default ? ' ★' : ''}`}
                      </option>
                    ))}
                  </optgroup>
                )}
                {templates.other_projects.length > 0 && (
                  <optgroup label="다른 프로젝트 양식">
                    {templates.other_projects.map((t) => (
                      <option key={`o-${t.id}`} value={`id:${t.id}`}>
                        {`${t.name} (${t.project_name ?? `프로젝트 #${t.schedule_id}`})`}
                      </option>
                    ))}
                  </optgroup>
                )}
                <optgroup label="기본 제공 양식">
                  <option value="builtin">기본 제공 양식 쓰기</option>
                </optgroup>
              </select>
            </label>
            <label className="rp-field">
              <span>특기사항 (선택)</span>
              <input value={createExtra} onChange={(e) => setCreateExtra(e.target.value)} placeholder="예: 골조 3층 타설 완료 강조" />
            </label>
            <div className="rp-form-btns">
              <Button variant="primary" onClick={() => void handleGenerate()} disabled={busy !== null}>
                작성 시작
              </Button>
              <Button onClick={() => setCreateOpen(false)}>취소</Button>
            </div>
          </div>
        )}

        <div className="rp-side-scroll">
          <div className="rp-grp">보고서 이력</div>
          {filteredReports.length === 0 ? (
            <p className="rp-empty-side">작성된 보고서가 없습니다.</p>
          ) : (
            filteredReports.map((r) => (
              <div key={r.id} className={`rp-list-row${activeReport?.id === r.id ? ' is-on' : ''}`}>
                <button type="button" className="rp-li" onClick={() => void openReport(r.id)}>
                  <b>{r.title}</b>
                  <small>{`${CADENCE_TEXT[r.cadence]} · ${r.template_name} · v${r.schedule_version}`}</small>
                </button>
                <button
                  type="button"
                  className="rp-li-del"
                  aria-label={`${r.title} 삭제`}
                  onClick={async () => {
                    await deleteReport(scheduleId, r.id);
                    await refresh(activeReport?.id === r.id ? null : activeReport?.id);
                  }}
                >
                  ×
                </button>
              </div>
            ))
          )}

          <div className="rp-grp">현재 프로젝트 양식 (자동 기억)</div>
          {filterTpls(templates.current_project).length === 0 ? (
            <p className="rp-empty-side">학습·저장된 프로젝트 양식이 없습니다.</p>
          ) : (
            filterTpls(templates.current_project).map((t) => (
              <div
                key={`cur-${t.id}`}
                className={`rp-list-row${inspected?.templateId === t.id && inspected.mode === 'edit' ? ' is-on' : ''}`}
              >
                <button
                  type="button"
                  className="rp-li"
                  onClick={() => {
                    setInspected(toDraft(t, scheduleId));
                    setInspectorOpen(true);
                  }}
                >
                  <b>{t.name}</b>
                  <small>{`${CADENCE_TEXT[t.cadence]}${t.is_default ? ' · 기본 적용' : ''} · 항목 ${t.sections.length}개`}</small>
                </button>
                <button
                  type="button"
                  className="rp-li-del"
                  aria-label={`${t.name} 양식 삭제`}
                  onClick={() => t.id !== null && void handleDeleteTemplate(t.id)}
                >
                  ×
                </button>
              </div>
            ))
          )}

          <div className="rp-grp">다른 프로젝트 양식 (선택 · 복사 가능)</div>
          {filterTpls(templates.other_projects).length === 0 ? (
            <p className="rp-empty-side">다른 프로젝트에 저장된 양식이 없습니다.</p>
          ) : (
            filterTpls(templates.other_projects).map((t) => (
              <div key={`oth-${t.id}`} className={`rp-list-row${inspected?.templateId === t.id ? ' is-on' : ''}`}>
                <button
                  type="button"
                  className="rp-li"
                  onClick={() => {
                    setInspected(toDraft(t, scheduleId));
                    setInspectorOpen(true);
                  }}
                >
                  <b>{t.name}</b>
                  <small>{`${t.project_name ?? `프로젝트 #${t.schedule_id}`} · ${CADENCE_TEXT[t.cadence]} · 항목 ${t.sections.length}개`}</small>
                </button>
              </div>
            ))
          )}

          <div className="rp-grp">기본 제공 양식</div>
          {filterTpls(templates.builtins).map((t) => (
            <div key={t.builtin_key} className={`rp-list-row${inspected?.isBuiltin && inspected.cadence === t.cadence ? ' is-on' : ''}`}>
              <button
                type="button"
                className="rp-li"
                onClick={() => {
                  setInspected(toDraft(t, scheduleId));
                  setInspectorOpen(true);
                }}
              >
                <b>{t.name}</b>
                <small>{`${CADENCE_TEXT[t.cadence]} · 기본 제공 · 항목 ${t.sections.length}개`}</small>
              </button>
            </div>
          ))}
        </div>

        {learnOpen && (
          <div className="rp-form-box rp-learn-box" role="region" aria-label="보고서 양식 파일 학습">
            <div className="rp-seg" role="group" aria-label="학습할 보고 주기">
              {(['monthly', 'quarterly'] as const).map((c) => (
                <button key={c} type="button" aria-pressed={learnCadence === c} onClick={() => setLearnCadence(c)}>
                  {c === 'monthly' ? '월간 양식' : '분기 양식'}
                </button>
              ))}
            </div>
            <label className="rp-field">
              <span>기존 보고서 파일 (docx · pptx · xlsx · pdf · md · 이미지)</span>
              <input
                type="file"
                aria-label="양식 파일 선택"
                accept=".docx,.pptx,.xlsx,.pdf,.hwpx,.csv,.tsv,.txt,.md,.png,.jpg,.jpeg,.webp"
                onChange={(e) => setLearnFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="rp-field">
              <span>양식 이름 (비우면 자동 추천)</span>
              <input value={learnName} onChange={(e) => setLearnName(e.target.value)} placeholder="예: 발주처 월간 표준 양식" />
            </label>
            <div className="rp-form-btns">
              <Button variant="primary" disabled={!learnFile || busy !== null} onClick={() => void handleLearnFile()}>
                {busy === 'learn' ? '양식 분석 중…' : '양식 분석 · 학습'}
              </Button>
              <Button onClick={() => setLearnOpen(false)}>닫기</Button>
            </div>
          </div>
        )}

        <div className="rp-side-foot">
          <Button className="rp-full-btn" onClick={() => setLearnOpen((v) => !v)} disabled={busy !== null}>
            + 양식 등록 (파일 올리기)
          </Button>
        </div>
      </aside>

      <section className="rp-main" aria-label="보고서 미리 보기 및 편집">
        <div className="rp-toolbar">
          {activeReport ? (
            <>
              <b className="rp-tb-title">{activeReport.title}</b>
              <Badge tone="info">{CADENCE_TEXT[activeReport.cadence]}</Badge>
              <span className="rp-tb-tpl">{activeReport.template_name}</span>
              <span className="rp-gap" />
              <Button onClick={() => void handleSaveReportContent()} disabled={busy !== null}>
                내용 저장
              </Button>
              <Button onClick={() => void handleRegenerate()} disabled={busy !== null}>
                다시 만들기
              </Button>
              <Button
                onClick={() => void exportReportFile(scheduleId, activeReport.id, 'html', activeReport.title)}
                disabled={busy !== null}
              >
                PDF 인쇄
              </Button>
              <Button
                variant="primary"
                onClick={() => void exportReportFile(scheduleId, activeReport.id, 'docx', activeReport.title)}
                disabled={busy !== null}
              >
                Word (.docx)
              </Button>
            </>
          ) : (
            <>
              <b>월간 · 분기별 공정 보고서</b>
              <span className="rp-gap" />
            </>
          )}
          <Button aria-pressed={inspectorOpen} onClick={() => setInspectorOpen((v) => !v)}>
            양식·말투 패널
          </Button>
        </div>

        {notice && (
          <div className="rp-banner is-info" role="status">
            <span>{notice}</span>
            <button type="button" aria-label="알림 닫기" onClick={() => setNotice(null)}>
              ×
            </button>
          </div>
        )}
        {error && (
          <div className="rp-banner is-error" role="alert">
            <span>{error}</span>
            <button type="button" aria-label="오류 닫기" onClick={() => setError(null)}>
              ×
            </button>
          </div>
        )}

        <div className="rp-canvas">
          {activeReport ? (
            <article className="rp-sheet" aria-label="보고서 본문">
              <header className="rp-sheet-head">
                <input
                  className="rp-title-input"
                  aria-label="보고서 제목"
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                />
                <div className="rp-meta-line">
                  {`${projectName || `일정 #${scheduleId}`} · ${activeReport.period_label} · 기준일 ${
                    dataDate ? dot(dataDate) : activeReport.data_date
                  } · v${activeReport.schedule_version} · 작성 ${activeReport.created_by}`}
                </div>
              </header>

              {draftBlocks.map((blk, idx) => (
                <section key={blk.id} className="rp-block">
                  <h2>{blk.heading}</h2>

                  {blk.block_kind === 'kpi' && (
                    <div className="rp-kpi-grid">
                      {blk.metrics.map((m, i) => (
                        <div key={i} className="rp-kpi-card">
                          <div className="rp-kpi-label">{m.label}</div>
                          <div className="rp-kpi-val">{m.value}</div>
                          {m.sub && <div className="rp-kpi-sub">{m.sub}</div>}
                        </div>
                      ))}
                    </div>
                  )}

                  {blk.block_kind === 'table' &&
                    (blk.table && blk.table.rows.length > 0 ? (
                      <table className="rp-table">
                        <thead>
                          <tr>
                            {blk.table.columns.map((c, i) => (
                              <th key={i}>{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {blk.table.rows.map((row, ri) => (
                            <tr key={ri}>
                              {row.map((cell, ci) => (
                                <td key={ci}>{cell ?? '—'}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <p className="rp-muted">{blk.text || '해당 자료가 없습니다.'}</p>
                    ))}

                  {blk.block_kind === 'chart' && (
                    <div className="rp-chart-wrap">
                      {blk.chart && <ReportChart chart={blk.chart} />}
                      {blk.text && <p className="rp-chart-cap">{blk.text}</p>}
                    </div>
                  )}

                  {(blk.block_kind === 'prose' || blk.block_kind === 'manual') && (
                    <div className="rp-prose-box">
                      {blk.auto_text && (
                        <div className="rp-auto-note" role="note" aria-label={`${blk.heading} 자동 문안 안내`}>
                          <span>AI 서술을 받지 못해 자동 문안으로 채웠습니다 —</span>
                          <button
                            type="button"
                            className="rp-mini-link"
                            onClick={() => void handleRegenerate()}
                            disabled={busy !== null}
                          >
                            다시 만들기
                          </button>
                        </div>
                      )}
                      <textarea
                        className="rp-textarea"
                        rows={blk.block_kind === 'prose' ? 4 : 3}
                        aria-label={`${blk.heading} 본문`}
                        value={blk.text}
                        placeholder={blk.block_kind === 'manual' ? '직접 입력할 내용을 적어 주세요.' : ''}
                        onChange={(e) => {
                          const text = e.target.value;
                          setDraftBlocks((prev) => prev.map((b, i) => (i === idx ? { ...b, text, auto_text: false } : b)));
                        }}
                      />
                      <div className="rp-prose-foot">
                        <button
                          type="button"
                          className="rp-mini-link"
                          onClick={() => setReviseTarget((cur) => (cur === blk.id ? null : blk.id))}
                        >
                          에이전트에게 고쳐 달라고 하기
                        </button>
                      </div>
                      {reviseTarget === blk.id && (
                        <div className="rp-revise-box">
                          <input
                            aria-label="수정 지침"
                            value={reviseInstruction}
                            onChange={(e) => setReviseInstruction(e.target.value)}
                            placeholder="예: 준공 지연 원인을 첫 줄에 강조하고 개조식으로 다듬어 줘"
                          />
                          <label className="rp-check-inline">
                            <input type="checkbox" checked={reviseRemember} onChange={(e) => setReviseRemember(e.target.checked)} />
                            <span>다음 보고서에도 이 규칙 기억</span>
                          </label>
                          <Button variant="primary" disabled={!reviseInstruction.trim() || busy !== null} onClick={() => void handleReviseBlock(blk.id)}>
                            적용
                          </Button>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              ))}
            </article>
          ) : (
            <div className="rp-empty-canvas">
              <h3>아직 선택된 보고서가 없습니다</h3>
              <p className="rp-muted">
                월간·분기별 공정 보고서를 바로 작성하거나, 기존 보고서 양식 파일을 올려 프로젝트에 학습·기억시킬 수 있습니다.
              </p>
              <div className="rp-empty-btns">
                <Button variant="primary" onClick={() => void handleGenerate('monthly')} disabled={busy !== null}>
                  월간 보고서 바로 만들기
                </Button>
                <Button onClick={() => void handleGenerate('quarterly')} disabled={busy !== null}>
                  분기별 보고서 바로 만들기
                </Button>
                <Button onClick={() => setLearnOpen(true)} disabled={busy !== null}>
                  + 양식 파일 학습하기
                </Button>
              </div>
            </div>
          )}
        </div>
      </section>

      {inspectorOpen && inspected && (
        <aside className="rp-inspector" aria-label="양식 연결 및 말투 기억">
          <div className="rp-ins-tabs">
            <button
              type="button"
              className={inspectorTab === 'sections' ? 'rp-ins-tab is-on' : 'rp-ins-tab'}
              onClick={() => setInspectorTab('sections')}
            >
              양식 항목
            </button>
            <button
              type="button"
              className={inspectorTab === 'style' ? 'rp-ins-tab is-on' : 'rp-ins-tab'}
              onClick={() => setInspectorTab('style')}
            >
              말투·표기
            </button>
          </div>

          <div className="rp-ins-scroll">
            {!readOnlyTpl && inspected.mode === 'new' && (
              <div className="rp-cross-banner" role="status">
                <div>
                  <b>분석된 양식 초안입니다 (아직 저장 전)</b>
                  <p>항목별 자료 연결을 확인·수정한 뒤 아래 「이 프로젝트에 양식 기억」 버튼을 눌러 저장하세요.</p>
                </div>
              </div>
            )}

            {inspected.mode === 'readonly' && !inspected.isBuiltin && (
              <div className="rp-cross-banner">
                <div>
                  <b>{`다른 프로젝트(${inspected.sourceProjectName ?? '타 프로젝트'})에서 학습된 양식`}</b>
                  <p>현재 프로젝트에 복사해 기본 양식으로 기억하거나, 이 양식으로 바로 보고서를 생성할 수 있습니다.</p>
                </div>
                <div className="rp-cross-btns">
                  <Button variant="primary" onClick={() => void handleAdoptTemplate()} disabled={busy !== null}>
                    이 프로젝트 양식으로 복사·기억
                  </Button>
                  <Button
                    onClick={() => {
                      setCreateOpen(true);
                      setCreateCadence(inspected.cadence);
                      if (inspected.templateId !== null) setCreateTplChoice(`id:${inspected.templateId}`);
                    }}
                  >
                    이 양식으로 작성
                  </Button>
                </div>
              </div>
            )}

            {inspected.isBuiltin && (
              <div className="rp-cross-banner">
                <p>기본 제공 양식입니다. 양식을 올려 학습하거나 새 양식으로 저장해 프로젝트별로 기억할 수 있습니다.</p>
                <Button
                  onClick={() =>
                    setInspected({
                      ...inspected,
                      mode: 'new',
                      templateId: null,
                      isBuiltin: false,
                      isDefault: true,
                      name: `${projectName || '현재 프로젝트'} ${CADENCE_TEXT[inspected.cadence]} 맞춤 양식`,
                    })
                  }
                >
                  현재 프로젝트 양식으로 복제·편집
                </Button>
              </div>
            )}

            {inspectorTab === 'sections' ? (
              <div className="rp-ins-pane">
                <label className="rp-field">
                  <span>양식 이름</span>
                  <input
                    value={inspected.name}
                    disabled={readOnlyTpl}
                    onChange={(e) => setInspected({ ...inspected, name: e.target.value })}
                  />
                </label>

                <div className="rp-row-between">
                  <span className="rp-muted">보고 주기</span>
                  <div className="rp-seg" role="group" aria-label="양식 주기">
                    {(['monthly', 'quarterly'] as const).map((c) => (
                      <button
                        key={c}
                        type="button"
                        disabled={readOnlyTpl}
                        aria-pressed={inspected.cadence === c}
                        onClick={() => setInspected({ ...inspected, cadence: c })}
                      >
                        {CADENCE_TEXT[c]}
                      </button>
                    ))}
                  </div>
                </div>

                {!readOnlyTpl && (
                  <label className="rp-check-inline">
                    <input
                      type="checkbox"
                      checked={inspected.isDefault}
                      onChange={(e) => setInspected({ ...inspected, isDefault: e.target.checked })}
                    />
                    <span>이 프로젝트의 기본 양식으로 자동 기억·적용</span>
                  </label>
                )}

                <div className="rp-sec-list">
                  {inspected.sections.map((sec, idx) => {
                    const isManual = sec.data_binding === 'manual_input';
                    return (
                      <div key={sec.id} className="rp-sec-card">
                        <div className="rp-sec-top">
                          <input
                            className="rp-sec-head-in"
                            aria-label={`항목 ${idx + 1} 제목`}
                            disabled={readOnlyTpl}
                            value={sec.heading}
                            onChange={(e) => updateSection(idx, { heading: e.target.value })}
                          />
                          <Badge tone={isManual ? 'neutral' : 'success'}>{isManual ? '직접 입력' : '연결됨'}</Badge>
                        </div>
                        <select
                          className="rp-sec-select"
                          aria-label={`${sec.heading} 연결 자료`}
                          disabled={readOnlyTpl}
                          value={sec.data_binding}
                          onChange={(e) => {
                            const binding = e.target.value as DataBinding;
                            updateSection(idx, { data_binding: binding, block_kind: bindingKindOf(binding) });
                          }}
                        >
                          {BINDING_OPTIONS.map((opt) => (
                            <option key={opt.value} value={opt.value}>
                              {opt.label}
                            </option>
                          ))}
                        </select>
                        {!readOnlyTpl && (
                          <div className="rp-sec-ctrls">
                            <button type="button" onClick={() => moveSection(idx, -1)} disabled={idx === 0}>
                              ↑
                            </button>
                            <button
                              type="button"
                              onClick={() => moveSection(idx, 1)}
                              disabled={idx === inspected.sections.length - 1}
                            >
                              ↓
                            </button>
                            <button type="button" onClick={() => removeSection(idx)} disabled={inspected.sections.length <= 1}>
                              삭제
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {!readOnlyTpl && (
                  <div className="rp-ins-foot">
                    <Button onClick={addSection}>+ 항목 추가</Button>
                    <Button variant="primary" onClick={() => void handleSaveTemplate()} disabled={busy !== null}>
                      {inspected.mode === 'new' ? '이 프로젝트에 양식 기억' : '양식 변경 저장'}
                    </Button>
                  </div>
                )}
              </div>
            ) : (
              <div className="rp-ins-pane">
                <label className="rp-field">
                  <span>학습된 문체 · 어조</span>
                  <input
                    disabled={readOnlyTpl}
                    value={inspected.style.tone}
                    onChange={(e) => setInspected({ ...inspected, style: { ...inspected.style, tone: e.target.value } })}
                  />
                </label>
                <label className="rp-field">
                  <span>날짜 표기 형식</span>
                  <select
                    disabled={readOnlyTpl}
                    value={inspected.style.date_format}
                    onChange={(e) => setInspected({ ...inspected, style: { ...inspected.style, date_format: e.target.value } })}
                  >
                    <option value="YYYY.MM.DD">2027.06.01 (YYYY.MM.DD)</option>
                    <option value="YYYY-MM-DD">2027-06-01 (YYYY-MM-DD)</option>
                    <option value="MM.DD">06.01 (MM.DD)</option>
                  </select>
                </label>
                <label className="rp-field">
                  <span>공정률 소수점 자리</span>
                  <select
                    disabled={readOnlyTpl}
                    value={inspected.style.number_precision}
                    onChange={(e) =>
                      setInspected({ ...inspected, style: { ...inspected.style, number_precision: Number(e.target.value) } })
                    }
                  >
                    <option value={0}>정수 (28%)</option>
                    <option value={1}>소수 1자리 (28.1%)</option>
                    <option value={2}>소수 2자리 (28.12%)</option>
                  </select>
                </label>

                <div className="rp-rules-box">
                  <span className="rp-muted">기억된 작성 규칙 ({inspected.style.learned_rules.length}개)</span>
                  {inspected.style.learned_rules.length === 0 ? (
                    <p className="rp-empty-side">아직 등록된 개별 지침이 없습니다.</p>
                  ) : (
                    <ul className="rp-rules-list">
                      {inspected.style.learned_rules.map((r, i) => (
                        <li key={i}>
                          <span>{r}</span>
                          {!readOnlyTpl && (
                            <button
                              type="button"
                              aria-label={`${r} 규칙 제거`}
                              onClick={() =>
                                setInspected({
                                  ...inspected,
                                  style: {
                                    ...inspected.style,
                                    learned_rules: inspected.style.learned_rules.filter((_, j) => j !== i),
                                  },
                                })
                              }
                            >
                              ×
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                  {!readOnlyTpl && (
                    <div className="rp-rule-add">
                      <input
                        value={newRuleText}
                        onChange={(e) => setNewRuleText(e.target.value)}
                        placeholder="예: 지연 항목마다 책임 주체 명시"
                      />
                      <Button
                        onClick={() => {
                          const txt = newRuleText.trim();
                          if (!txt) return;
                          setInspected({
                            ...inspected,
                            style: { ...inspected.style, learned_rules: [...inspected.style.learned_rules, txt] },
                          });
                          setNewRuleText('');
                        }}
                      >
                        추가
                      </Button>
                    </div>
                  )}
                </div>

                {!readOnlyTpl && (
                  <div className="rp-ins-foot">
                    <Button variant="primary" onClick={() => void handleSaveTemplate()} disabled={busy !== null}>
                      말투·규칙 저장
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
