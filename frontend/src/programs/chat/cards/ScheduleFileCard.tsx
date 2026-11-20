// 공정표 파일 감지 카드(card:schedule_file). [일정 초안으로 가져오기]로 에이전트에게 요청한다.
import Button from '../../../shared/ui/Button';
import { useChat } from '../chatStore';
import { asList, asNum, asText, Card, type CardProps } from './Card';

export default function ScheduleFileCard({ data }: CardProps) {
  const fileId = asNum(data.file_id);
  const sheet = asText(data.sheet);
  const rows = asNum(data.rows);
  const found = asList(data.columns_found).map((v) => String(v));
  const missing = asList(data.missing).map((v) => String(v));

  function importDraft() {
    if (fileId === null) return;
    void useChat.getState().send(`이 파일로 일정 초안을 만들어 줘(#${fileId})`);
  }

  return (
    <Card title="공정표 파일">
      <p className="ch-wrap">
        {sheet ? `시트 「${sheet}」` : '표'}
        {rows !== null ? ` · ${rows.toLocaleString()}행` : ''}
      </p>
      {found.length > 0 && <p className="ch-muted ch-wrap">{`찾은 열: ${found.join(', ')}`}</p>}
      {missing.length > 0 && <p className="ch-muted ch-wrap">{`비어 있는 열: ${missing.join(', ')}`}</p>}
      {fileId !== null && (
        <div className="ch-actions">
          <Button variant="primary" onClick={importDraft}>
            일정 초안으로 가져오기
          </Button>
        </div>
      )}
    </Card>
  );
}
