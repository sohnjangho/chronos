"""Liner Visualization 시험용 가짜 서버와 HTML. 네트워크를 쓰지 않는다(httpx.MockTransport).

HTML 모양은 실측(11-20, stream:false) 그대로 줄였다: 머리에 CDN 셋(design-token CSS·pretendard CSS·Chart.js UMD),
보이는 표(<td>), 그리고 `const data = [{…}]` 배열 → `.map` → `new Chart(ctx, {… scales.x.min/max: new Date('…')})`.
"""

import asyncio
import json

import httpx

CDN = (  # 실측 HTML 의 외부 주소 그대로
    "https://cdn.jsdelivr.net/npm/@liner-fe/design-token@^3.0.0/lib/index.css",
    "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css",
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js",
)


def chart_html(rows: list[list], *, bounds: tuple[str, str] | None = ("2027-03-01", "2027-07-15"),
               extra_data: str = "", extra_script: str = "", visible: bool = True, chart: bool = True) -> str:
    """rows(표의 줄)를 담은 Liner 모양 HTML. extra_data 는 data 배열 끝에 더할 항목 글, extra_script 는 차트 뒤 글."""
    def cell(v: object) -> str:
        return json.dumps(v, ensure_ascii=False)

    items = [f"    {{ {', '.join(f'c{i}: {cell(v)}' for i, v in enumerate(r))} }}" for r in rows]
    if extra_data:
        items.append(f"    {extra_data}")
    table = "".join(f"<tr>{''.join(f'<td>{v}</td>' for v in r)}</tr>" for r in rows) if visible else ""
    scales = (f"x: {{ min: new Date('{bounds[0]}').getTime(), max: new Date('{bounds[1]}').getTime(), "
              "ticks: { callback: function(value) { return value; } } }") if bounds else "x: {}"
    script = f"""
  const colors = ['#185FA5', '#993c1d', 'rgba(24, 95, 165, 0.4)'];
  const data = [
{(',' + chr(10)).join(items)}
  ];
  const labels = data.map(d => d.c0);
  const values = data.map(d => new Date(d.c1).getTime());
  new Chart(ctx, {{
    type: 'bar',
    data: {{ labels: labels, datasets: [{{ label: '계획 끝', data: values, backgroundColor: colors[0], borderWidth: 1.5 }}] }},
    options: {{ indexAxis: 'y', scales: {{ {scales} }} }}
  }});""" if chart else "\n  document.body.dataset.ready = '1';"
    return f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="{CDN[0]}">
<link rel="stylesheet" href="{CDN[1]}">
<style>body {{ margin: 0; }}</style></head><body><div id="vis-container">
<canvas id="c"></canvas><table><tbody>{table}</tbody></table>
<script src="{CDN[2]}"></script>
<script>
(function() {{
  const ctx = document.getElementById('c').getContext('2d');{script}{extra_script}
}})();
</script></div></body></html>"""


def atlas_body(html: str, *, theme: str = "comparison", resource_id: str = "viz_test1") -> dict:
    """stream:false 응답(실측): {chunks: [start, start-step, data-atlas, finish-step, finish]}."""
    return {"chunks": [
        {"type": "start", "messageId": "m1", "messageMetadata": {"requestId": "r1", "traceId": "api_visualization_1"}},
        {"type": "start-step"},
        {"type": "data-atlas", "data": {"atlasArtifact": {
            "html": html, "theme": theme, "description": "작업별 계획과 전망 비교", "resourceId": resource_id}}},
        {"type": "finish-step"},
        {"type": "finish"},
    ]}


class VisualMock(httpx.MockTransport):
    """replies 를 차례로 답한다(다 쓰면 마지막을 되풀이). dict → 200 JSON, int → 그 상태(빈 JSON), 예외 → 던짐.

    delay 초를 기다린 뒤 답한다(동시에 도는 요청을 시험할 때 — 0 이면 기다리지 않아 요청이 겹치지 않는다).
    """

    def __init__(self, *replies: object, delay: float = 0.0) -> None:
        self.requests: list[httpx.Request] = []
        self.replies = list(replies)
        self.delay = delay
        super().__init__(self._handle)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        reply = self.replies[min(len(self.requests), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, int):
            return httpx.Response(reply, json={})
        return httpx.Response(200, json=reply)
