// 「보고서」 화면의 상태와 동작. ReportsTab 과 그 조각(목록 · 본문 · 양식 패널)이 함께 쓴다.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError } from '../../shared/api';
import { useSchedule, useScheduleStore } from '../../shared/schedule/scope';
import {
  BINDING_OPTIONS,
  adoptTemplate,
  createTemplate,
  deleteTemplate,
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

export interface DraftTemplateState {
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

export function toDraft(tpl: ReportTemplateItem, currentScheduleId: number): DraftTemplateState {
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

export function bindingKindOf(binding: DataBinding) {
  return BINDING_OPTIONS.find((b) => b.value === binding)?.kind ?? 'manual';
}

export const CADENCE_TEXT: Record<Cadence, string> = { monthly: '월간', quarterly: '분기' };

/** 화면의 모든 상태(서버 목록 · 고른 보고서와 고치는 중인 본문 · 양식 패널 · 작성/학습 칸 · 알림). */
function useReportsState() {
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

  return {
    scheduleId, projectName, dataDate,
    reports, setReports, templates, setTemplates, cadenceFilter, setCadenceFilter,
    activeReport, draftTitle, setDraftTitle, draftBlocks, setDraftBlocks,
    inspectorOpen, setInspectorOpen, inspectorTab, setInspectorTab, inspected, setInspected,
    createOpen, setCreateOpen, createCadence, setCreateCadence, createPeriod, setCreatePeriod,
    createTplChoice, setCreateTplChoice, createExtra, setCreateExtra,
    learnOpen, setLearnOpen, learnFile, setLearnFile, learnCadence, setLearnCadence, learnName, setLearnName,
    reviseTarget, setReviseTarget, reviseInstruction, setReviseInstruction, reviseRemember, setReviseRemember,
    newRuleText, setNewRuleText,
    busy, setBusy, notice, setNotice, error, setError,
    syncReportDraft,
  };
}

type ReportsState = ReturnType<typeof useReportsState>;
type Refresh = (selectReportId?: number | null) => Promise<void>;

/** 보고서·양식 목록을 다시 읽고, 고른(없으면 첫) 보고서와 그 양식을 연다. */
function useRefresh(st: ReportsState): Refresh {
  const { scheduleId, setTemplates, setReports, setError, syncReportDraft, setInspected } = st;
  return useCallback(
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
}

/** 보고서 열기 · 작성 · 다시 작성. */
function reportActions(st: ReportsState, refresh: Refresh) {
  const { scheduleId, templates, dataDate, setBusy, setError, setNotice, syncReportDraft, setInspected } = st;

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
    const cad = cadenceOverride ?? st.createCadence;
    setBusy('generate');
    setError(null);
    setNotice(null);
    try {
      let tplId: number | null = null;
      let useBuiltin = false;
      if (!cadenceOverride && st.createTplChoice) {
        if (st.createTplChoice === 'builtin') useBuiltin = true;
        else if (st.createTplChoice.startsWith('id:')) tplId = Number(st.createTplChoice.slice(3));
      }
      const created = await generateReport(scheduleId, {
        cadence: cad,
        template_id: tplId,
        use_builtin: useBuiltin,
        period_label: cadenceOverride ? defaultPeriod(dataDate, cad) : st.createPeriod.trim() || undefined,
        extra_note: cadenceOverride ? '' : st.createExtra.trim(),
      });
      st.setCreateOpen(false);
      st.setCreateExtra('');
      setNotice(`「${created.title}」 보고서를 작성했습니다.`);
      await refresh(created.id);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleRegenerate = async () => {
    if (!st.activeReport) return;
    setBusy('regen');
    setError(null);
    try {
      const updated = await regenerateReport(scheduleId, st.activeReport.id, {});
      syncReportDraft(updated);
      setNotice(`일정 v${updated.schedule_version} 기준으로 보고서를 다시 작성했습니다.`);
      await refresh(updated.id);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서를 다시 작성하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  return { openReport, handleGenerate, handleRegenerate };
}

/** 올린 양식 파일을 분석해 저장 전 양식 초안으로 연다. */
function learnAction(st: ReportsState) {
  const { scheduleId, setBusy, setError, setNotice } = st;
  const handleLearnFile = async () => {
    if (!st.learnFile) return;
    setBusy('learn');
    setError(null);
    setNotice(null);
    try {
      const uploaded = await uploadTemplateFile(st.learnFile);
      const learned = await learnTemplate({
        file_id: uploaded.file_id,
        schedule_id: scheduleId,
        cadence: st.learnCadence,
        name: st.learnName.trim() || undefined,
      });
      st.setInspected({
        mode: 'new',
        templateId: null,
        sourceProjectName: st.projectName || null,
        sourceFileId: learned.source_file_id,
        sourceFileName: learned.source_file_name,
        name: learned.suggested_name,
        cadence: learned.suggested_cadence,
        isDefault: true,
        isBuiltin: false,
        sections: learned.sections,
        style: learned.style,
      });
      st.setInspectorOpen(true);
      st.setInspectorTab('sections');
      st.setLearnOpen(false);
      st.setLearnFile(null);
      st.setLearnName('');
      setNotice(`${learned.analysis_summary} 오른쪽 패널에서 매핑과 말투를 확인한 뒤 저장하세요.`);
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식 파일을 분석하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };
  return { handleLearnFile };
}

/** 양식 패널의 양식 저장(새로 기억 · 고친 것 저장). */
function saveTemplateAction(st: ReportsState) {
  const { scheduleId, inspected, setBusy, setError, setNotice } = st;
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
      st.setTemplates(tplRes);
      st.setInspected(toDraft(saved, scheduleId));
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '양식을 저장하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };
  return { handleSaveTemplate };
}

/** 다른 프로젝트 양식 복사 · 학습된 양식 삭제. */
function templateActions(st: ReportsState) {
  const { scheduleId, inspected, setBusy, setError, setNotice, setTemplates, setInspected } = st;

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

  return { handleAdoptTemplate, handleDeleteTemplate };
}

/** 본문 저장 · 항목 하나를 에이전트에게 고쳐 달라고 하기. */
function contentActions(st: ReportsState) {
  const { scheduleId, activeReport, setBusy, setError, setNotice, syncReportDraft } = st;

  const handleSaveReportContent = async () => {
    if (!activeReport) return;
    setBusy('save-rep');
    setError(null);
    try {
      const saved = await updateReport(scheduleId, activeReport.id, {
        title: st.draftTitle.trim() || activeReport.title,
        blocks: st.draftBlocks,
      });
      syncReportDraft(saved);
      st.setReports((prev) => prev.map((r) => (r.id === saved.id ? { ...r, title: saved.title, updated_at: saved.updated_at } : r)));
      setNotice('보고서 수정 내용을 저장했습니다.');
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '보고서를 저장하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  const handleReviseBlock = async (blockId: string) => {
    if (!activeReport || !st.reviseInstruction.trim()) return;
    setBusy('revise');
    setError(null);
    try {
      const updated = await reviseReportBlock(scheduleId, activeReport.id, {
        block_id: blockId,
        instruction: st.reviseInstruction.trim(),
        remember_rule: st.reviseRemember,
      });
      syncReportDraft(updated);
      st.setReviseTarget(null);
      st.setReviseInstruction('');
      if (st.reviseRemember) {
        const tplRes = await listTemplates(scheduleId);
        st.setTemplates(tplRes);
        const matched = updated.template_id ? tplRes.current_project.find((t) => t.id === updated.template_id) : undefined;
        if (matched) st.setInspected(toDraft(matched, scheduleId));
      }
      setNotice(st.reviseRemember ? '항목을 수정하고 프로젝트 양식 규칙에 기억했습니다.' : '항목을 수정했습니다.');
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : '항목 수정을 처리하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  };

  return { handleSaveReportContent, handleReviseBlock };
}

/** 양식 항목 고치기 · 옮기기 · 더하기 · 빼기. */
function sectionEditors(st: ReportsState) {
  const { inspected, setInspected } = st;

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

  return { updateSection, moveSection, addSection, removeSection };
}

/** 「보고서」 화면 하나의 상태와 동작을 모두 모은다. */
export function useReportsController() {
  const st = useReportsState();
  const refresh = useRefresh(st);
  const { setInspected, setCreateOpen, setLearnOpen, setNotice, setCreatePeriod, dataDate, createCadence, reports, cadenceFilter } = st;

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

  return {
    ...st,
    refresh,
    filteredReports,
    filterTpls,
    readOnlyTpl: st.inspected?.mode === 'readonly',
    ...reportActions(st, refresh),
    ...learnAction(st),
    ...saveTemplateAction(st),
    ...templateActions(st),
    ...contentActions(st),
    ...sectionEditors(st),
  };
}

export type ReportsCtl = ReturnType<typeof useReportsController>;
