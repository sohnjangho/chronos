// [+ 만약에 복사본]: 바꿔 볼 것을 글로 받아 에이전트 대화에 맡긴다(복사본은 에이전트가 scenario 도구로 만든다).
import { useState } from 'react';
import { useWindows } from '../../os/windowStore';
import Button from '../../shared/ui/Button';
import Dialog from './Dialog';

export default function WhatIfDialog({ onClose }: { onClose(): void }) {
  const [text, setText] = useState('');
  const ask = text.trim();
  const send = () => {
    useWindows.getState().open('chat', { ask: `만약에 복사본을 만들어 줘: ${ask}` });
    onClose();
  };
  return (
    <Dialog
      title="만약에 복사본"
      onClose={onClose}
      actions={
        <>
          <Button variant="primary" disabled={!ask} onClick={send}>
            에이전트에게 맡기기
          </Button>
          <Button onClick={onClose}>취소</Button>
        </>
      }
    >
      <label className="cmp-field">
        <span>무엇을 바꿔 볼까요?</span>
        <textarea
          rows={3}
          value={text}
          autoFocus
          placeholder="예: 타워크레인을 2대로 하면?"
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <p className="cmp-dialog-p is-muted">일정은 그대로 두고 복사본을 만들어 이 비교판에 띄웁니다.</p>
    </Dialog>
  );
}
