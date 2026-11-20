// CPM 그림 판: 관계선 아래, 카드 위. 판 안에서만 스크롤하고(창은 밀리지 않음) 확대·축소·맞춤은 왼쪽 아래.
import { useId, useMemo, type RefObject } from 'react';
import type { ScheduleView } from '../../shared/schedule/scheduleApi';
import type { Layers } from './cards';
import Edges, { ArrowDefs } from './Edges';
import type { Network } from './layout';
import NodeCard from './NodeCard';
import { ZOOM_STEP, type Net } from './useNetwork';

interface CanvasProps {
  view: ScheduleView;
  graph: Network;
  net: Net;
  layers: Layers;
  selected: string | null;
  editing: string | null;
  svgRef: RefObject<SVGSVGElement | null>;
  onEdge(key: string): void;
}

export default function Canvas({ view, graph, net, layers, selected, editing, svgRef, onEdge }: CanvasProps) {
  const arrow = `cpm-arrow-${useId().replace(/[^\w-]/g, '')}`;
  const acts = useMemo(() => new Map(view.activities.map((a) => [a.id, a])), [view]);
  const { w, h } = net.size;
  return (
    <div className="cpm-stage">
      <div className="cpm-canvas" ref={net.canvasRef}>
        <svg
          data-network ref={svgRef} className="cpm-svg" role="group" aria-label="CPM 네트워크"
          width={w * net.zoom} height={h * net.zoom} viewBox={`0 0 ${w} ${h}`}
        >
          <ArrowDefs arrow={arrow} />
          <Edges edges={graph.edges} pos={net.pos} cpm={layers.cpm} editing={editing} arrow={arrow} onPick={onEdge} />
          {graph.nodes.map((n) => {
            const p = net.pos.get(n.id)!;
            return (
              <NodeCard
                key={n.id} a={acts.get(n.id)!} x={p.x} y={p.y} layers={layers} selected={selected === n.id}
                onDown={net.onDown} onKey={net.onKey}
              />
            );
          })}
        </svg>
        {graph.nodes.length === 0 && <p className="cpm-empty">이 보기에 보일 액티비티가 없습니다.</p>}
      </div>
      <div className="cpm-zoom" role="group" aria-label="확대·축소">
        <button type="button" aria-label="확대" onClick={() => net.zoomBy(ZOOM_STEP)}>
          +
        </button>
        <button type="button" aria-label="축소" onClick={() => net.zoomBy(1 / ZOOM_STEP)}>
          −
        </button>
        <button type="button" aria-label="화면에 맞춤" onClick={net.fit}>
          맞춤
        </button>
      </div>
    </div>
  );
}
