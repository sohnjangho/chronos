// 「보고서」 왼쪽 칸: 보고서 만들기 · 보고서 이력 · 양식 목록 · 양식 파일 학습.
import Button from '../../shared/ui/Button';
import { deleteReport } from './reportsApi';
import { CADENCE_TEXT, toDraft, type ReportsCtl } from './reportsController';

function CreateForm({ c }: { c: ReportsCtl }) {
  const { templates } = c;
  return (
    <div className="rp-form-box" role="region" aria-label="새 보고서 설정">
      <div className="rp-seg" role="group" aria-label="보고 주기 선택">
        {(['monthly', 'quarterly'] as const).map((cad) => (
          <button key={cad} type="button" aria-pressed={c.createCadence === cad} onClick={() => c.setCreateCadence(cad)}>
            {cad === 'monthly' ? '월간 보고서' : '분기별 보고서'}
          </button>
        ))}
      </div>
      <label className="rp-field">
        <span>보고 기간</span>
        <input value={c.createPeriod} onChange={(e) => c.setCreatePeriod(e.target.value)} placeholder="예: 2027년 6월" />
      </label>
      <label className="rp-field">
        <span>적용할 양식</span>
        <select aria-label="적용할 양식" value={c.createTplChoice} onChange={(e) => c.setCreateTplChoice(e.target.value)}>
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
        <input value={c.createExtra} onChange={(e) => c.setCreateExtra(e.target.value)} placeholder="예: 골조 3층 타설 완료 강조" />
      </label>
      <div className="rp-form-btns">
        <Button variant="primary" onClick={() => void c.handleGenerate()} disabled={c.busy !== null}>
          작성 시작
        </Button>
        <Button onClick={() => c.setCreateOpen(false)}>취소</Button>
      </div>
    </div>
  );
}

function ReportHistory({ c }: { c: ReportsCtl }) {
  const { activeReport } = c;
  return (
    <>
      <div className="rp-grp">보고서 이력</div>
      {c.filteredReports.length === 0 ? (
        <p className="rp-empty-side">작성된 보고서가 없습니다.</p>
      ) : (
        c.filteredReports.map((r) => (
          <div key={r.id} className={`rp-list-row${activeReport?.id === r.id ? ' is-on' : ''}`}>
            <button type="button" className="rp-li" onClick={() => void c.openReport(r.id)}>
              <b>{r.title}</b>
              <small>{`${CADENCE_TEXT[r.cadence]} · ${r.template_name} · v${r.schedule_version}`}</small>
            </button>
            <button
              type="button"
              className="rp-li-del"
              aria-label={`${r.title} 삭제`}
              onClick={async () => {
                await deleteReport(c.scheduleId, r.id);
                await c.refresh(activeReport?.id === r.id ? null : activeReport?.id);
              }}
            >
              ×
            </button>
          </div>
        ))
      )}
    </>
  );
}

function TemplateLists({ c }: { c: ReportsCtl }) {
  const { templates, inspected, filterTpls, scheduleId } = c;
  const pick = (t: Parameters<typeof toDraft>[0]) => {
    c.setInspected(toDraft(t, scheduleId));
    c.setInspectorOpen(true);
  };
  return (
    <>
      <div className="rp-grp">현재 프로젝트 양식 (자동 기억)</div>
      {filterTpls(templates.current_project).length === 0 ? (
        <p className="rp-empty-side">학습·저장된 프로젝트 양식이 없습니다.</p>
      ) : (
        filterTpls(templates.current_project).map((t) => (
          <div
            key={`cur-${t.id}`}
            className={`rp-list-row${inspected?.templateId === t.id && inspected.mode === 'edit' ? ' is-on' : ''}`}
          >
            <button type="button" className="rp-li" onClick={() => pick(t)}>
              <b>{t.name}</b>
              <small>{`${CADENCE_TEXT[t.cadence]}${t.is_default ? ' · 기본 적용' : ''} · 항목 ${t.sections.length}개`}</small>
            </button>
            <button
              type="button"
              className="rp-li-del"
              aria-label={`${t.name} 양식 삭제`}
              onClick={() => t.id !== null && void c.handleDeleteTemplate(t.id)}
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
            <button type="button" className="rp-li" onClick={() => pick(t)}>
              <b>{t.name}</b>
              <small>{`${t.project_name ?? `프로젝트 #${t.schedule_id}`} · ${CADENCE_TEXT[t.cadence]} · 항목 ${t.sections.length}개`}</small>
            </button>
          </div>
        ))
      )}

      <div className="rp-grp">기본 제공 양식</div>
      {filterTpls(templates.builtins).map((t) => (
        <div key={t.builtin_key} className={`rp-list-row${inspected?.isBuiltin && inspected.cadence === t.cadence ? ' is-on' : ''}`}>
          <button type="button" className="rp-li" onClick={() => pick(t)}>
            <b>{t.name}</b>
            <small>{`${CADENCE_TEXT[t.cadence]} · 기본 제공 · 항목 ${t.sections.length}개`}</small>
          </button>
        </div>
      ))}
    </>
  );
}

function LearnForm({ c }: { c: ReportsCtl }) {
  return (
    <div className="rp-form-box rp-learn-box" role="region" aria-label="보고서 양식 파일 학습">
      <div className="rp-seg" role="group" aria-label="학습할 보고 주기">
        {(['monthly', 'quarterly'] as const).map((cad) => (
          <button key={cad} type="button" aria-pressed={c.learnCadence === cad} onClick={() => c.setLearnCadence(cad)}>
            {cad === 'monthly' ? '월간 양식' : '분기 양식'}
          </button>
        ))}
      </div>
      <label className="rp-field">
        <span>기존 보고서 파일 (docx · pptx · xlsx · pdf · md · 이미지)</span>
        <input
          type="file"
          aria-label="양식 파일 선택"
          accept=".docx,.pptx,.xlsx,.pdf,.hwpx,.csv,.tsv,.txt,.md,.png,.jpg,.jpeg,.webp"
          onChange={(e) => c.setLearnFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <label className="rp-field">
        <span>양식 이름 (비우면 자동 추천)</span>
        <input value={c.learnName} onChange={(e) => c.setLearnName(e.target.value)} placeholder="예: 발주처 월간 표준 양식" />
      </label>
      <div className="rp-form-btns">
        <Button variant="primary" disabled={!c.learnFile || c.busy !== null} onClick={() => void c.handleLearnFile()}>
          {c.busy === 'learn' ? '양식 분석 중…' : '양식 분석 · 학습'}
        </Button>
        <Button onClick={() => c.setLearnOpen(false)}>닫기</Button>
      </div>
    </div>
  );
}

export default function ReportsSidebar({ c }: { c: ReportsCtl }) {
  return (
    <aside className="rp-sidebar" aria-label="보고서와 양식 목록">
      <div className="rp-side-actions">
        <Button variant="primary" onClick={() => c.setCreateOpen((v) => !v)} disabled={c.busy !== null}>
          + 보고서 만들기
        </Button>
        <div className="rp-seg" role="group" aria-label="보고 주기 필터">
          {(['all', 'monthly', 'quarterly'] as const).map((cad) => (
            <button key={cad} type="button" aria-pressed={c.cadenceFilter === cad} onClick={() => c.setCadenceFilter(cad)}>
              {cad === 'all' ? '전체' : cad === 'monthly' ? '월간' : '분기'}
            </button>
          ))}
        </div>
      </div>

      {c.createOpen && <CreateForm c={c} />}

      <div className="rp-side-scroll">
        <ReportHistory c={c} />
        <TemplateLists c={c} />
      </div>

      {c.learnOpen && <LearnForm c={c} />}

      <div className="rp-side-foot">
        <Button className="rp-full-btn" onClick={() => c.setLearnOpen((v) => !v)} disabled={c.busy !== null}>
          + 양식 등록 (파일 올리기)
        </Button>
      </div>
    </aside>
  );
}
