// 입력창 위 파일 타일 트레이(시안 B) + 실패 까닭은 트레이 아래 한 줄.
import FileChip, { type ChipItem } from '../../shared/files/FileChip';

interface Props {
  items: ChipItem[];
  notice: string | null;
  onRemove(localId: string): void;
}

export default function FileChips({ items, notice, onRemove }: Props) {
  if (items.length === 0 && !notice) return null;
  const failed = items.filter((i) => i.status === 'failed' && i.reason);

  return (
    <div className="ch-file-tray" aria-label="붙인 파일">
      {items.length > 0 && (
        <div className="ch-file-list">
          {items.map((item) => (
            <FileChip key={item.localId} item={item} onRemove={() => onRemove(item.localId)} />
          ))}
        </div>
      )}
      {notice && (
        <p className="ch-file-err" role="alert">
          {notice}
        </p>
      )}
      {failed.map((f) => (
        <p key={f.localId} className="ch-file-err" role="alert">
          {`${f.name}: ${f.reason}`}
        </p>
      ))}
    </div>
  );
}
