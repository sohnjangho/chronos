// 대화 머리 오른쪽 「모델 ▾」 고르기(시안 A). 이 대화의 일반 답(normal)에만 적용된다.
import { useEffect, useState } from 'react';
import { listChatModels, type ChatModel, type ChatModelGroup } from './chatApi';
import { useChat } from './chatStore';

export default function ModelPicker() {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<ChatModelGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentId = useChat((s) => s.currentId);
  const threadModel = useChat((s) => (s.currentId === null ? s.pendingModel : (s.threads[s.currentId]?.model ?? null)));

  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoading(true);
    setError(null);
    listChatModels()
      .then((res) => {
        if (live) {
          setGroups(res.connections);
          setLoading(false);
        }
      })
      .catch(() => {
        if (live) {
          setError('모델 목록을 불러오지 못했습니다.');
          setLoading(false);
        }
      });
    return () => {
      live = false;
    };
  }, [open]);

  async function pick(m: ChatModel | null) {
    setOpen(false);
    if (m === null) {
      await useChat.getState().clearModel();
    } else {
      await useChat.getState().setModel(m);
    }
  }

  const label = threadModel ? threadModel.model : '기본 모델';

  return (
    <div className="ch-model-wrap" onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}>
      <button
        type="button"
        className="ch-pill ch-model-btn"
        aria-expanded={open}
        aria-label={`대화 모델 고르기: ${label}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="ch-ellipsis">{label}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="ch-model-pop" role="dialog" aria-label="대화 모델 고르기">
          <p className="ch-model-scope">
            이 대화의 일반 답에만 적용됩니다. 일정 생성·분류·그림 읽기는 설정 배정을 따릅니다.
          </p>
          <button
            type="button"
            className={`ch-model-opt ${!threadModel ? 'is-active' : ''}`}
            onClick={() => void pick(null)}
          >
            기본 모델(설정 배정)
          </button>
          {loading && <p className="ch-muted">불러오는 중…</p>}
          {error && <p className="ch-file-err">{error}</p>}
          {groups.map((g) => (
            <div key={g.connection_id} className="ch-model-group">
              <div className="ch-model-gname">{g.name}</div>
              {g.models.map((m) => {
                const active = threadModel?.connection_id === g.connection_id && threadModel.model === m.id;
                return (
                  <button
                    key={m.id}
                    type="button"
                    className={`ch-model-opt ${active ? 'is-active' : ''}`}
                    onClick={() =>
                      void pick({ connection_id: g.connection_id, model: m.id, routing_strategy: null })
                    }
                  >
                    <span>{m.name || m.id}</span>
                  </button>
                );
              })}
            </div>
          ))}
          {currentId === null && (
            <p className="ch-muted ch-model-hint">새 대화는 첫 메시지를 보낼 때 적용됩니다.</p>
          )}
        </div>
      )}
    </div>
  );
}
