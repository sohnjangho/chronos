// 차이 표: ID · 이름 · 구분 · 시작 차이 · 종료 차이 · OD(기준 → 비교). 차이는 서버가 센 근무일.
// 좁으면 표 안에서만 가로로 밀리고 ID·이름 칸은 고정이다.
import type { RowOut } from './compareApi';
import { cellText } from './Bar';
import { CHANGE_LABEL, deltaText, odText, toneOf } from './rows';

const titleOf = (r: RowOut) => [r.base && `기준 ${cellText(r.base)}`, r.other && `비교 ${cellText(r.other)}`].filter(Boolean).join('\n');

export default function DiffTable({ rows }: { rows: RowOut[] }) {
  return (
    <div className="cmp-diff" role="region" aria-label="차이 표">
      <table className="cmp-table">
        <thead>
          <tr>
            <th className="cmp-sticky cmp-id">ID</th>
            <th className="cmp-sticky2 cmp-name">이름</th>
            <th className="cmp-kind">구분</th>
            <th className="cmp-num">시작 차이</th>
            <th className="cmp-num">종료 차이</th>
            <th className="cmp-num cmp-od">OD (기준 → 비교)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.activity_id} data-testid={`diff-${r.activity_id}`} title={titleOf(r)}>
              <td className="cmp-sticky cmp-id">{r.activity_id}</td>
              <td className="cmp-sticky2 cmp-name">{r.name}</td>
              <td className="cmp-kind">
                <i className={`cmp-swatch is-${r.change}`} aria-hidden="true" />
                {CHANGE_LABEL[r.change]}
              </td>
              <td className={`cmp-num ${toneOf(r.start_delta)}`}>{deltaText(r.start_delta)}</td>
              <td className={`cmp-num ${toneOf(r.finish_delta)}`}>{deltaText(r.finish_delta)}</td>
              <td className="cmp-num cmp-od">{odText(r)}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={6} className="cmp-empty">
                달라진 액티비티가 없습니다.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
