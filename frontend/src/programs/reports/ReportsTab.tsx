// 「보고서」 화면: 월간·분기별 보고서 생성, 프로젝트별 학습 양식 기억, 타 프로젝트 양식 선택·복사, PDF/Word 내보내기.
// 상태와 동작은 reportsController, 왼쪽 목록 · 가운데 본문 · 오른쪽 양식 패널은 각 조각 파일에 있다.
import ReportInspector from './ReportInspector';
import ReportsMain from './ReportsMain';
import ReportsSidebar from './ReportsSidebar';
import { useReportsController } from './reportsController';
import './reports.css';

export default function ReportsTab() {
  const c = useReportsController();
  return (
    <div className="rp-root">
      <ReportsSidebar c={c} />
      <ReportsMain c={c} />
      {c.inspectorOpen && c.inspected && <ReportInspector c={c} inspected={c.inspected} />}
    </div>
  );
}
