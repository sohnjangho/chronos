// 「CPM」 화면(시안 「일정판 CPM」): 도구줄 · 요약 줄 넷 · 네트워크 그림(SVG) · 오른쪽 「상세」.
// 고르기는 일정 저장소(같은 일정을 보는 창들이 따라온다), 관계 고치기는 저장소의 선행 쓰기. 날짜·여유는 모두 서버 값.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import { useNotify, useSchedule, useSelect, useWindowId } from '../../shared/schedule/scope';
import Canvas from './Canvas';
import type { Layers } from './cards';
import CpmSummary from './CpmSummary';
import CpmToolbar from './CpmToolbar';
import DetailPanel from './DetailPanel';
import { exportPng } from './exportPng';
import { edgeKey, layoutNetwork, type ViewMode } from './layout';
import RelationEditor from './RelationEditor';
import { useNetwork, type Net } from './useNetwork';
import './cpm.css';

const counts = (v: ScheduleView) =>
  `노드 ${v.activities.length} · 관계 ${v.relations.length} · 크리티컬 ${v.summary.critical_count} · 음수 플로트 ${v.summary.negative_float_count}`;

/** 다른 창에서 고르면 그 카드를 가운데로. 이 창(또는 모든 창)에 온 보이기 요청(params.activity)이면 보기를 풀고 가운데로. */
function useFollow(net: Net, showAll: () => void) {
  const windowId = useWindowId();
  const selected = useSchedule((s) => s.selected);
  const selectedBy = useSchedule((s) => s.selectedBy);
  const selectedN = useSchedule((s) => s.selectedN);
  const reveal = useSchedule((s) => s.reveal);
  const { centerSoon } = net;
  useEffect(() => {
    if (selected && selectedBy && selectedBy !== windowId) centerSoon(selected);
  }, [selectedN, selected, selectedBy, windowId, centerSoon]);
  const seen = useRef(reveal?.n ?? 0);
  useEffect(() => {
    if (!reveal || reveal.n === seen.current) return;
    seen.current = reveal.n;
    if (reveal.by !== null && reveal.by !== windowId) return;
    showAll();
    centerSoon(reveal.aid);
  }, [reveal, windowId, centerSoon, showAll]);
}

export default function CpmTab() {
  const view = useSchedule((s) => s.view)!;
  const selected = useSchedule((s) => s.selected);
  const select = useSelect();
  const notify = useNotify();
  const [layers, setLayers] = useState<Layers>({ plan: true, actual: true, cpm: true });
  const [mode, setMode] = useState<ViewMode>('all');
  const [wbs, setWbs] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const focus = mode === 'selected' ? selected : null;
  const graph = useMemo(() => layoutNetwork(view, { mode, selected: focus, wbs }), [view, mode, focus, wbs]);
  const net = useNetwork(graph, select);
  const svgRef = useRef<SVGSVGElement>(null);
  const showAll = useCallback(() => {
    setMode('all');
    setWbs(null);
  }, []);
  useFollow(net, showAll);

  const rel = editing ? (view.relations.find((r) => edgeKey(r) === editing) ?? null) : null;
  const wbsGroups = useMemo(() => view.wbs.filter((w) => !w.parent), [view]);

  function find(text: string) {
    const q = text.trim().toLowerCase();
    if (!q) return;
    const hit = view.activities.find((a) => a.id.toLowerCase().includes(q) || a.name.toLowerCase().includes(q));
    if (!hit) return notify('error', `찾는 액티비티가 없습니다: ${text.trim()}`);
    if (mode !== 'selected' && !graph.nodes.some((n) => n.id === hit.id)) showAll();
    select(hit.id);
    net.centerSoon(hit.id);
  }

  function png() {
    if (!svgRef.current) return;
    exportPng(svgRef.current, `${view.name} v${view.version} CPM`).catch(() => notify('error', '그림을 만들지 못했습니다.'));
  }

  return (
    <div className="cpm-tab">
      <CpmToolbar
        layers={layers} onLayer={(k) => setLayers((l) => ({ ...l, [k]: !l[k] }))} mode={mode} onMode={setMode} hasSelection={!!selected}
        onFind={find} onAutoLayout={net.autoLayout} onFit={net.fit} wbsGroups={wbsGroups} wbs={wbs} onWbs={setWbs} onPng={png}
        counts={counts(view)}
      />
      <CpmSummary scheduleId={view.id} version={view.version} />
      <div className="cpm-main">
        <Canvas view={view} graph={graph} net={net} layers={layers} selected={selected} editing={rel ? editing : null} svgRef={svgRef} onEdge={setEditing} />
        <DetailPanel
          view={view} selected={selected} onEdit={setEditing}
          editor={rel && <RelationEditor key={editing} rel={rel} onClose={() => setEditing(null)} />}
        />
      </div>
    </div>
  );
}
