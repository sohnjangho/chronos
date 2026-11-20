// 자료 저장·분류 완료 카드(card:file_saved).
import { useWindows } from '../../../os/windowStore';
import Button from '../../../shared/ui/Button';
import { asObj, asText, Card, type CardProps } from './Card';

export default function FileSavedCard({ data }: CardProps) {
  const name = asText(data.name) || `파일 #${asText(data.file_id)}`;
  const axes = asObj(data.axes);
  const tags = Object.entries(axes).flatMap(([axis, vals]) =>
    Array.isArray(vals) ? vals.map((v) => `${axis}: ${String(v)}`) : [],
  );

  return (
    <Card title="자료함에 저장됨">
      <p className="ch-card-title ch-wrap">{name}</p>
      {tags.length > 0 && (
        <div className="ch-card-chips">
          {tags.map((t) => (
            <span key={t} className="ch-mini-chip">
              {t}
            </span>
          ))}
        </div>
      )}
      <div className="ch-actions">
        <Button onClick={() => useWindows.getState().open('library')}>자료함 열기</Button>
      </div>
    </Card>
  );
}
