// 「보고서」 가운데 칸: 도구 줄 · 알림 · 보고서 본문(항목별 블록) 또는 빈 화면.
import { dot } from '../../shared/schedule/format';
import Badge from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import { ReportChart } from './ReportCharts';
import { CADENCE_TEXT, type ReportsCtl } from './reportsController';
import { exportReportFile, type ReportBlock, type ReportDetail } from './reportsApi';

function Toolbar({ c }: { c: ReportsCtl }) {
  const { activeReport, busy, scheduleId } = c;
  return (
    <div className="rp-toolbar">
      {activeReport ? (
        <>
          <b className="rp-tb-title">{activeReport.title}</b>
          <Badge tone="info">{CADENCE_TEXT[activeReport.cadence]}</Badge>
          <span className="rp-tb-tpl">{activeReport.template_name}</span>
          <span className="rp-gap" />
          <Button onClick={() => void c.handleSaveReportContent()} disabled={busy !== null}>
            내용 저장
          </Button>
          <Button onClick={() => void c.handleRegenerate()} disabled={busy !== null}>
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
      <Button aria-pressed={c.inspectorOpen} onClick={() => c.setInspectorOpen((v) => !v)}>
        양식·말투 패널
      </Button>
    </div>
  );
}

function TableBlock({ blk }: { blk: ReportBlock }) {
  return blk.table && blk.table.rows.length > 0 ? (
    <table className="rp-table">
      <thead>
        <tr>
          {blk.table.columns.map((col, i) => (
            <th key={i}>{col}</th>
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
  );
}

function ProseBlock({ c, blk, idx }: { c: ReportsCtl; blk: ReportBlock; idx: number }) {
  return (
    <div className="rp-prose-box">
      {blk.auto_text && (
        <div className="rp-auto-note" role="note" aria-label={`${blk.heading} 자동 문안 안내`}>
          <span>AI 서술을 받지 못해 자동 문안으로 채웠습니다 —</span>
          <button type="button" className="rp-mini-link" onClick={() => void c.handleRegenerate()} disabled={c.busy !== null}>
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
          c.setDraftBlocks((prev) => prev.map((b, i) => (i === idx ? { ...b, text, auto_text: false } : b)));
        }}
      />
      <div className="rp-prose-foot">
        <button type="button" className="rp-mini-link" onClick={() => c.setReviseTarget((cur) => (cur === blk.id ? null : blk.id))}>
          에이전트에게 고쳐 달라고 하기
        </button>
      </div>
      {c.reviseTarget === blk.id && (
        <div className="rp-revise-box">
          <input
            aria-label="수정 지침"
            value={c.reviseInstruction}
            onChange={(e) => c.setReviseInstruction(e.target.value)}
            placeholder="예: 준공 지연 원인을 첫 줄에 강조하고 개조식으로 다듬어 줘"
          />
          <label className="rp-check-inline">
            <input type="checkbox" checked={c.reviseRemember} onChange={(e) => c.setReviseRemember(e.target.checked)} />
            <span>다음 보고서에도 이 규칙 기억</span>
          </label>
          <Button variant="primary" disabled={!c.reviseInstruction.trim() || c.busy !== null} onClick={() => void c.handleReviseBlock(blk.id)}>
            적용
          </Button>
        </div>
      )}
    </div>
  );
}

function Sheet({ c, report }: { c: ReportsCtl; report: ReportDetail }) {
  const { projectName, scheduleId, dataDate } = c;
  return (
    <article className="rp-sheet" aria-label="보고서 본문">
      <header className="rp-sheet-head">
        <input className="rp-title-input" aria-label="보고서 제목" value={c.draftTitle} onChange={(e) => c.setDraftTitle(e.target.value)} />
        <div className="rp-meta-line">
          {`${projectName || `일정 #${scheduleId}`} · ${report.period_label} · 기준일 ${
            dataDate ? dot(dataDate) : report.data_date
          } · v${report.schedule_version} · 작성 ${report.created_by}`}
        </div>
      </header>

      {c.draftBlocks.map((blk, idx) => (
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

          {blk.block_kind === 'table' && <TableBlock blk={blk} />}

          {blk.block_kind === 'chart' && (
            <div className="rp-chart-wrap">
              {blk.chart && <ReportChart chart={blk.chart} />}
              {blk.text && <p className="rp-chart-cap">{blk.text}</p>}
            </div>
          )}

          {(blk.block_kind === 'prose' || blk.block_kind === 'manual') && <ProseBlock c={c} blk={blk} idx={idx} />}
        </section>
      ))}
    </article>
  );
}

function EmptyCanvas({ c }: { c: ReportsCtl }) {
  return (
    <div className="rp-empty-canvas">
      <h3>아직 선택된 보고서가 없습니다</h3>
      <p className="rp-muted">
        월간·분기별 공정 보고서를 바로 작성하거나, 기존 보고서 양식 파일을 올려 프로젝트에 학습·기억시킬 수 있습니다.
      </p>
      <div className="rp-empty-btns">
        <Button variant="primary" onClick={() => void c.handleGenerate('monthly')} disabled={c.busy !== null}>
          월간 보고서 바로 만들기
        </Button>
        <Button onClick={() => void c.handleGenerate('quarterly')} disabled={c.busy !== null}>
          분기별 보고서 바로 만들기
        </Button>
        <Button onClick={() => c.setLearnOpen(true)} disabled={c.busy !== null}>
          + 양식 파일 학습하기
        </Button>
      </div>
    </div>
  );
}

export default function ReportsMain({ c }: { c: ReportsCtl }) {
  return (
    <section className="rp-main" aria-label="보고서 미리 보기 및 편집">
      <Toolbar c={c} />

      {c.notice && (
        <div className="rp-banner is-info" role="status">
          <span>{c.notice}</span>
          <button type="button" aria-label="알림 닫기" onClick={() => c.setNotice(null)}>
            ×
          </button>
        </div>
      )}
      {c.error && (
        <div className="rp-banner is-error" role="alert">
          <span>{c.error}</span>
          <button type="button" aria-label="오류 닫기" onClick={() => c.setError(null)}>
            ×
          </button>
        </div>
      )}

      <div className="rp-canvas">{c.activeReport ? <Sheet c={c} report={c.activeReport} /> : <EmptyCanvas c={c} />}</div>
    </section>
  );
}
