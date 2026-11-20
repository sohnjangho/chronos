import Badge from '../shared/ui/Badge';
import { useApprovals } from './approvals';
import { programs } from './registry';
import { useSession } from './session';
import { useWindows } from './windowStore';

/** 등록된 프로그램. 누르면 열기 · 앞으로 · 최소화 복귀(모두 windowStore.open). */
export default function Dock() {
  const role = useSession((s) => s.session?.user.role ?? 'user');
  const wins = useWindows((s) => s.wins);
  const open = useWindows((s) => s.open);
  const pending = useApprovals((s) => s.pending);
  return (
    <nav className="os-dock" aria-label="Dock">
      {programs(role).map((p) => {
        const running = wins.some((w) => w.programId === p.id);
        const badge = p.badge === 'approvals' ? pending : 0;
        return (
          <button
            key={p.id}
            type="button"
            className={`os-dock-icon os-kind-${p.kind}`}
            aria-label={p.name}
            title={p.name}
            data-running={running}
            onClick={() => open(p.id)}
          >
            {p.icon}
            {running && <span className="os-dock-dot" aria-hidden="true" />}
            {badge > 0 && (
              <Badge tone="danger" solid className="os-dock-badge">
                {badge}
              </Badge>
            )}
          </button>
        );
      })}
    </nav>
  );
}
