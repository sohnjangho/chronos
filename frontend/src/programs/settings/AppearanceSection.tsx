import { useState } from 'react';
import { useDock } from '../../os/dockStore';
import { getProgram } from '../../os/registry';
import { useTheme, type Theme } from '../../os/theme';
import { useZoom } from '../../os/zoom';
import Button from '../../shared/ui/Button';

const THEMES: { id: Theme; title: string; subtitle: string; previewClass: string }[] = [
  { id: 'light', title: '주간 모드 (Daylight Sky)', subtitle: '맑은 하늘색 그라데이션 바탕과 밝은 유리 카드', previewClass: 'is-light' },
  { id: 'dark', title: '야간 모드 (Midnight Aurora)', subtitle: '깊은 네이비 오로라 바탕과 저눈부심 다크 패널', previewClass: 'is-dark' },
];

/** 「화면 · 테마」: 주간/야간 모드 전환, 프로그램별 창 배율 초기화, Dock 고정 구성 복원. */
export default function AppearanceSection() {
  const theme = useTheme((s) => s.theme);
  const setTheme = useTheme((s) => s.setTheme);
  const levels = useZoom((s) => s.levels);
  const resetZoom = useZoom((s) => s.reset);
  const resetAllZoom = useZoom((s) => s.resetAll);
  const pinned = useDock((s) => s.pinned);
  const resetDock = useDock((s) => s.resetDefault);
  const [notice, setNotice] = useState<string | null>(null);

  const customZooms = Object.entries(levels).filter(([, pct]) => pct !== 100);

  return (
    <div className="st-pane">
      <div className="st-section-head">
        <h2>화면 · 테마</h2>
        <p className="st-muted">바탕화면 색상 테마, 프로그램 창 배율(Zoom), 하단 Dock 구성을 관리합니다.</p>
      </div>

      <section className="st-card" aria-label="화면 테마 선택">
        <div className="st-card-head">
          <b className="st-card-name">주간 / 야간 모드</b>
          <span className="st-gap" />
          <span className="st-muted">{`현재: ${theme === 'dark' ? '야간 모드' : '주간 모드'}`}</span>
        </div>
        <div className="st-theme-grid" role="group" aria-label="테마 선택">
          {THEMES.map((item) => {
            const active = theme === item.id;
            return (
              <button
                key={item.id}
                type="button"
                className="st-theme-card"
                aria-pressed={active}
                onClick={() => {
                  setTheme(item.id);
                  setNotice(null);
                }}
              >
                <span className={`st-theme-preview ${item.previewClass}`} aria-hidden="true">
                  <span className="st-tp-bar" />
                  <span className="st-tp-win" />
                </span>
                <span className="st-theme-meta">
                  <b>{item.title}</b>
                  <span className="st-muted">{item.subtitle}</span>
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section className="st-card" aria-label="창 화면 배율">
        <div className="st-card-head">
          <b className="st-card-name">창 화면 배율 (Zoom)</b>
          <span className="st-gap" />
          <Button
            disabled={customZooms.length === 0}
            onClick={() => {
              resetAllZoom();
              setNotice('모든 창의 배율을 100%로 초기화했습니다.');
            }}
          >
            모든 창 배율 100%로 초기화
          </Button>
        </div>
        {customZooms.length === 0 ? (
          <p className="st-muted">모든 프로그램 창이 기본 배율(100%)로 열립니다.</p>
        ) : (
          <ul className="st-chip-list" aria-label="배율이 변경된 프로그램">
            {customZooms.map(([id, pct]) => (
              <li key={id} className="st-chip-item">
                <span>{`${getProgram(id)?.name ?? id}: ${pct}%`}</span>
                <button type="button" className="st-chip-reset" aria-label={`${getProgram(id)?.name ?? id} 배율 초기화`} onClick={() => resetZoom(id)}>
                  100%
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="st-card" aria-label="Dock 구성">
        <div className="st-card-head">
          <b className="st-card-name">Dock 고정 구성</b>
          <span className="st-gap" />
          <Button
            disabled={pinned === null}
            onClick={() => {
              resetDock();
              setNotice('Dock 구성을 기본값으로 복원했습니다.');
            }}
          >
            Dock 기본 구성으로 복원
          </Button>
        </div>
        <p className="st-muted">
          {pinned === null
            ? '현재 기본 Dock 구성을 사용 중입니다. (메뉴바 「보기」나 앱 서랍에서 아이콘을 고정·해제할 수 있습니다.)'
            : `사용자 지정 Dock 사용 중 · 고정 프로그램 ${pinned.length}개`}
        </p>
      </section>

      {notice && (
        <p className="st-ok" role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
