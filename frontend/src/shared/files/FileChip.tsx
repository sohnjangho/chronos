// 공용 파일 칩/타일(시안 B 타일 트레이: 사진은 썸네일 타일, 문서는 아이콘 카드, 실패 까닭은 트레이 아래).
export interface ChipItem {
  localId: string;
  fileId: number | null;
  name: string;
  kind: string;
  status: 'uploading' | 'received' | 'extracted' | 'indexed' | 'classified' | 'failed';
  reason: string | null;
  axes: Record<string, string[]>;
  thumbUrl: string | null;
  resized: boolean;
}

function firstAxisValue(axes: Record<string, string[]>): string | null {
  for (const key of ['종류', '공종', '현장', '시기', '출처']) {
    const val = axes[key]?.[0];
    if (val) return val;
  }
  return null;
}

export function chipStatusText(item: ChipItem): string {
  if (item.status === 'uploading') return '올리는 중';
  if (item.status === 'failed') return '✕ 실패';
  if (item.status === 'received') return '읽는 중';
  if (item.status === 'classified') {
    const tag = firstAxisValue(item.axes);
    return tag ? `저장됨 · ${tag}` : '저장됨';
  }
  if (item.status === 'extracted' && item.reason && item.reason.includes('뜻 검색')) {
    return '뜻 검색 준비 안 됨';
  }
  if (item.status === 'indexed' || item.status === 'extracted') {
    const tag = firstAxisValue(item.axes);
    return tag ? `저장됨 · ${tag}` : '읽는 중';
  }
  return '읽는 중';
}

const KIND_ICON: Record<string, string> = {
  pdf: 'PDF',
  sheet: 'XLS',
  table: 'CSV',
  doc: 'DOC',
  text: 'TXT',
  image: 'IMG',
};

export default function FileChip({ item, onRemove }: { item: ChipItem; onRemove?: () => void }) {
  const status = chipStatusText(item);
  const isImage = item.kind === 'image' && item.thumbUrl;

  return (
    <div className={`ch-file-tile is-${item.status}`} data-file-id={item.fileId ?? undefined}>
      {isImage ? (
        <img src={item.thumbUrl!} alt={item.name} className="ch-file-thumb" />
      ) : (
        <span className="ch-file-icon" aria-hidden="true">
          {KIND_ICON[item.kind] ?? 'FILE'}
        </span>
      )}
      <div className="ch-file-info">
        <span className="ch-file-name" title={item.name}>
          {item.name}
        </span>
        <span className="ch-file-status">{status}</span>
        {item.resized && <span className="ch-file-note">크기를 줄여 올렸습니다</span>}
      </div>
      {onRemove && (
        <button
          type="button"
          className="ch-file-x"
          aria-label={`${item.name} 빼기`}
          onClick={onRemove}
        >
          ×
        </button>
      )}
    </div>
  );
}
