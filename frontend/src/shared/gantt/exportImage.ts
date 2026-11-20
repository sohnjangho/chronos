// 그림 내보내기: 문서에 붙은 SVG 를 PNG 로(캔버스). 캔버스를 쓸 수 없으면 SVG 파일로 내려받는다.
// 화면 CSS(토큰 변수)는 그림 파일 안에서 읽히지 않으므로, 계산된 색·글꼴을 요소마다 style 로 옮겨 적는다.

const PROPS = [
  'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity',
  'font-family', 'font-size', 'font-weight', 'text-anchor', 'display', 'visibility',
];

function inlineStyles(src: Element, dst: Element) {
  const cs = getComputedStyle(src);
  const style = PROPS.map((p) => [p, cs.getPropertyValue(p)])
    .filter(([, v]) => v && !v.includes('var('))
    .map(([p, v]) => `${p}:${v}`)
    .join(';');
  if (style) dst.setAttribute('style', style);
  dst.removeAttribute('class');
  for (let i = 0; i < src.children.length; i += 1) inlineStyles(src.children[i], dst.children[i]);
}

/** 내려받기(주소는 받기가 시작된 뒤 푼다). */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function serialize(svg: SVGSVGElement, background: string): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('style', `background:${background}`);
  return new XMLSerializer().serializeToString(clone);
}

function toPng(xml: string, w: number, h: number, background: string, ctx: CanvasRenderingContext2D): Promise<Blob | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      ctx.canvas.toBlob((b) => resolve(b), 'image/png');
    };
    img.onerror = () => resolve(null);
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  });
}

/** svg(문서에 붙어 있어야 CSS 가 계산된다)를 '<fileBase>.png' 로, 못 하면 '<fileBase>.svg' 로 내려받는다. */
export async function downloadSvgImage(svg: SVGSVGElement, fileBase: string, background: string): Promise<'png' | 'svg'> {
  const xml = serialize(svg, background);
  const w = Number(svg.getAttribute('width'));
  const h = Number(svg.getAttribute('height'));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  const png = ctx ? await toPng(xml, w, h, background, ctx) : null;
  if (png) {
    saveBlob(png, `${fileBase}.png`);
    return 'png';
  }
  saveBlob(new Blob([xml], { type: 'image/svg+xml' }), `${fileBase}.svg`);
  return 'svg';
}
