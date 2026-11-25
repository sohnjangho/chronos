// 「보고서」 오른쪽 양식 패널: 양식 항목(자료 연결) · 말투·표기(기억된 작성 규칙).
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { BINDING_OPTIONS, type DataBinding, type TemplateSection } from './reportsApi';
import { CADENCE_TEXT, bindingKindOf, type DraftTemplateState, type ReportsCtl } from './reportsController';

interface PaneProps {
  c: ReportsCtl;
  inspected: DraftTemplateState;
}

function Banners({ c, inspected }: PaneProps) {
  return (
    <>
      {!c.readOnlyTpl && inspected.mode === 'new' && (
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
            <Button variant="primary" onClick={() => void c.handleAdoptTemplate()} disabled={c.busy !== null}>
              이 프로젝트 양식으로 복사·기억
            </Button>
            <Button
              onClick={() => {
                c.setCreateOpen(true);
                c.setCreateCadence(inspected.cadence);
                if (inspected.templateId !== null) c.setCreateTplChoice(`id:${inspected.templateId}`);
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
              c.setInspected({
                ...inspected,
                mode: 'new',
                templateId: null,
                isBuiltin: false,
                isDefault: true,
                name: `${c.projectName || '현재 프로젝트'} ${CADENCE_TEXT[inspected.cadence]} 맞춤 양식`,
              })
            }
          >
            현재 프로젝트 양식으로 복제·편집
          </Button>
        </div>
      )}
    </>
  );
}

function SectionCard({ c, inspected, sec, idx }: PaneProps & { sec: TemplateSection; idx: number }) {
  const readOnlyTpl = c.readOnlyTpl;
  const isManual = sec.data_binding === 'manual_input';
  return (
    <div className="rp-sec-card">
      <div className="rp-sec-top">
        <input
          className="rp-sec-head-in"
          aria-label={`항목 ${idx + 1} 제목`}
          disabled={readOnlyTpl}
          value={sec.heading}
          onChange={(e) => c.updateSection(idx, { heading: e.target.value })}
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
          c.updateSection(idx, { data_binding: binding, block_kind: bindingKindOf(binding) });
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
          <button type="button" onClick={() => c.moveSection(idx, -1)} disabled={idx === 0}>
            ↑
          </button>
          <button type="button" onClick={() => c.moveSection(idx, 1)} disabled={idx === inspected.sections.length - 1}>
            ↓
          </button>
          <button type="button" onClick={() => c.removeSection(idx)} disabled={inspected.sections.length <= 1}>
            삭제
          </button>
        </div>
      )}
    </div>
  );
}

function SectionsPane({ c, inspected }: PaneProps) {
  const readOnlyTpl = c.readOnlyTpl;
  return (
    <div className="rp-ins-pane">
      <label className="rp-field">
        <span>양식 이름</span>
        <input value={inspected.name} disabled={readOnlyTpl} onChange={(e) => c.setInspected({ ...inspected, name: e.target.value })} />
      </label>

      <div className="rp-row-between">
        <span className="rp-muted">보고 주기</span>
        <div className="rp-seg" role="group" aria-label="양식 주기">
          {(['monthly', 'quarterly'] as const).map((cad) => (
            <button
              key={cad}
              type="button"
              disabled={readOnlyTpl}
              aria-pressed={inspected.cadence === cad}
              onClick={() => c.setInspected({ ...inspected, cadence: cad })}
            >
              {CADENCE_TEXT[cad]}
            </button>
          ))}
        </div>
      </div>

      {!readOnlyTpl && (
        <label className="rp-check-inline">
          <input type="checkbox" checked={inspected.isDefault} onChange={(e) => c.setInspected({ ...inspected, isDefault: e.target.checked })} />
          <span>이 프로젝트의 기본 양식으로 자동 기억·적용</span>
        </label>
      )}

      <div className="rp-sec-list">
        {inspected.sections.map((sec, idx) => (
          <SectionCard key={sec.id} c={c} inspected={inspected} sec={sec} idx={idx} />
        ))}
      </div>

      {!readOnlyTpl && (
        <div className="rp-ins-foot">
          <Button onClick={c.addSection}>+ 항목 추가</Button>
          <Button variant="primary" onClick={() => void c.handleSaveTemplate()} disabled={c.busy !== null}>
            {inspected.mode === 'new' ? '이 프로젝트에 양식 기억' : '양식 변경 저장'}
          </Button>
        </div>
      )}
    </div>
  );
}

function RulesBox({ c, inspected }: PaneProps) {
  const readOnlyTpl = c.readOnlyTpl;
  const rules = inspected.style.learned_rules;
  return (
    <div className="rp-rules-box">
      <span className="rp-muted">기억된 작성 규칙 ({rules.length}개)</span>
      {rules.length === 0 ? (
        <p className="rp-empty-side">아직 등록된 개별 지침이 없습니다.</p>
      ) : (
        <ul className="rp-rules-list">
          {rules.map((r, i) => (
            <li key={i}>
              <span>{r}</span>
              {!readOnlyTpl && (
                <button
                  type="button"
                  aria-label={`${r} 규칙 제거`}
                  onClick={() =>
                    c.setInspected({
                      ...inspected,
                      style: { ...inspected.style, learned_rules: rules.filter((_, j) => j !== i) },
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
          <input value={c.newRuleText} onChange={(e) => c.setNewRuleText(e.target.value)} placeholder="예: 지연 항목마다 책임 주체 명시" />
          <Button
            onClick={() => {
              const txt = c.newRuleText.trim();
              if (!txt) return;
              c.setInspected({ ...inspected, style: { ...inspected.style, learned_rules: [...rules, txt] } });
              c.setNewRuleText('');
            }}
          >
            추가
          </Button>
        </div>
      )}
    </div>
  );
}

function StylePane({ c, inspected }: PaneProps) {
  const readOnlyTpl = c.readOnlyTpl;
  const setStyle = (patch: Partial<DraftTemplateState['style']>) => c.setInspected({ ...inspected, style: { ...inspected.style, ...patch } });
  return (
    <div className="rp-ins-pane">
      <label className="rp-field">
        <span>학습된 문체 · 어조</span>
        <input disabled={readOnlyTpl} value={inspected.style.tone} onChange={(e) => setStyle({ tone: e.target.value })} />
      </label>
      <label className="rp-field">
        <span>날짜 표기 형식</span>
        <select disabled={readOnlyTpl} value={inspected.style.date_format} onChange={(e) => setStyle({ date_format: e.target.value })}>
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
          onChange={(e) => setStyle({ number_precision: Number(e.target.value) })}
        >
          <option value={0}>정수 (28%)</option>
          <option value={1}>소수 1자리 (28.1%)</option>
          <option value={2}>소수 2자리 (28.12%)</option>
        </select>
      </label>

      <RulesBox c={c} inspected={inspected} />

      {!readOnlyTpl && (
        <div className="rp-ins-foot">
          <Button variant="primary" onClick={() => void c.handleSaveTemplate()} disabled={c.busy !== null}>
            말투·규칙 저장
          </Button>
        </div>
      )}
    </div>
  );
}

export default function ReportInspector({ c, inspected }: PaneProps) {
  return (
    <aside className="rp-inspector" aria-label="양식 연결 및 말투 기억">
      <div className="rp-ins-tabs">
        <button
          type="button"
          className={c.inspectorTab === 'sections' ? 'rp-ins-tab is-on' : 'rp-ins-tab'}
          onClick={() => c.setInspectorTab('sections')}
        >
          양식 항목
        </button>
        <button
          type="button"
          className={c.inspectorTab === 'style' ? 'rp-ins-tab is-on' : 'rp-ins-tab'}
          onClick={() => c.setInspectorTab('style')}
        >
          말투·표기
        </button>
      </div>

      <div className="rp-ins-scroll">
        <Banners c={c} inspected={inspected} />
        {c.inspectorTab === 'sections' ? <SectionsPane c={c} inspected={inspected} /> : <StylePane c={c} inspected={inspected} />}
      </div>
    </aside>
  );
}
