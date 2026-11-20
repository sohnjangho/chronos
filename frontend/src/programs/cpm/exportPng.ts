// PNG 내보내기: 화면의 네트워크 SVG → 글자(SVG) → 그림(Image) → 캔버스 → PNG 내려받기. 캔버스를 쓸 수 없으면 SVG 파일로.
// 화면 CSS(토큰 변수)는 그림 파일 안에서 읽히지 않으므로 계산된 색·글꼴을 요소마다 style 로 옮겨 적는다. 확대와 상관없이 원래 크기로.

const PROPS = [
  'fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity',
  'font-family', 'font-size', 'font-weight', 'text-anchor', 'dominant-baseline', 'display', 'visibility',
];
/** 캔버스가 받아 주는 크기 안으로(한 변 16000px, 넓이 1.2억 px). */
const MAX_SIDE = 16000;
const MAX_AREA = 120_000_000;

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

/** viewBox 의 원래 크기를 캔버스 한도 안으로 줄인 그림 크기. */
function pictureSize(svg: SVGSVGElement): { w: number; h: number; vw: number; vh: number } {
  const [, , vw, vh] = (svg.getAttribute('viewBox') ?? '').split(/\s+/).map(Number);
  const w0 = vw || Number(svg.getAttribute('width')) || 1;
  const h0 = vh || Number(svg.getAttribute('height')) || 1;
  const k = Math.min(1, MAX_SIDE / w0, MAX_SIDE / h0, Math.sqrt(MAX_AREA / (w0 * h0)));
  return { w: Math.max(1, Math.floor(w0 * k)), h: Math.max(1, Math.floor(h0 * k)), vw: w0, vh: h0 };
}

/** 그림 파일로 쓸 SVG 글(스타일을 요소에 적고, 원래 크기로). svg 는 문서에 붙어 있어야 CSS 가 계산된다. */
export function svgMarkup(svg: SVGSVGElement): string {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  inlineStyles(svg, clone);
  const { w, h, vw, vh } = pictureSize(svg);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  clone.setAttribute('viewBox', `0 0 ${vw} ${vh}`);
  clone.setAttribute('width', String(w));
  clone.setAttribute('height', String(h));
  return new XMLSerializer().serializeToString(clone);
}

function save(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function rasterize(xml: string, w: number, h: number, background: string): Promise<Blob | null> {
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return Promise.resolve(null);
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      canvas.toBlob((b) => resolve(b), 'image/png');
    };
    img.onerror = () => resolve(null);
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;
  });
}

/** '<fileName>.png' 로 내려받는다. 못 하면 '<fileName>.svg'. */
export async function exportPng(svg: SVGSVGElement, fileName: string): Promise<void> {
  const xml = svgMarkup(svg);
  const { w, h } = pictureSize(svg);
  const background = getComputedStyle(document.documentElement).getPropertyValue('--bg-panel').trim() || '#ffffff';
  const png = await rasterize(xml, w, h, background);
  if (png) save(png, `${fileName}.png`);
  else save(new Blob([xml], { type: 'image/svg+xml' }), `${fileName}.svg`);
}
