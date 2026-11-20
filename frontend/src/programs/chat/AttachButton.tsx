// 입력창 📎 파일 첨부 단추.
import { useRef } from 'react';

interface Props {
  disabled?: boolean;
  onPick(files: File[]): void;
}

export default function AttachButton({ disabled, onPick }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button
        type="button"
        className="ch-attach-btn"
        aria-label="파일 붙이기"
        title="파일 붙이기 (최대 10개, 파일당 50MB)"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        📎
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        aria-label="파일 선택"
        onChange={(e) => {
          const list = e.target.files ? Array.from(e.target.files) : [];
          e.target.value = '';
          if (list.length > 0) onPick(list);
        }}
      />
    </>
  );
}
