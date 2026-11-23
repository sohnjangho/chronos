// 그림 크기 줄이기: 원본이 base64 5MiB 안이면 그대로, 넘으면 긴 변 maxEdge(1568) 로 줄인 사본을 만든다.
// always 면 크기와 상관없이 긴 변 maxEdge 의 JPEG(quality) 로 다시 만든다(현장 사진 올리기).
export const MAX_BASE64_BYTES = 5 * 1024 * 1024;
export const DEFAULT_MAX_EDGE = 1568;
const RESIZABLE_TYPES = new Set(['image/png', 'image/jpeg', 'image/webp']);

export const base64BytesOf = (rawBytes: number) => Math.ceil(rawBytes / 3) * 4;

export interface ResizeOptions {
  /** 크기와 상관없이 늘 줄이고 JPEG 로 다시 만든다. */
  always?: boolean;
  /** JPEG·webp 품질(기본 0.85). */
  quality?: number;
}

export interface ResizeResult {
  file: File;
  resized: boolean;
}

function loadHtmlImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('그림을 읽을 수 없습니다.'));
    };
    img.src = url;
  });
}

function canvasToBlob(canvas: HTMLCanvasElement, mime: string, quality: number): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, mime, quality));
}

/** png·jpg·webp 가 base64 5MiB 를 넘으면(always 면 늘) 긴 변을 maxEdge 로 줄인다. 캔버스가 없거나 줄이기 실패면 원본 그대로. */
export async function resizeImage(file: File, maxEdge = DEFAULT_MAX_EDGE, opts: ResizeOptions = {}): Promise<ResizeResult> {
  if (!RESIZABLE_TYPES.has(file.type)) return { file, resized: false };
  if (!opts.always && base64BytesOf(file.size) <= MAX_BASE64_BYTES) return { file, resized: false };
  if (typeof document === 'undefined') return { file, resized: false };

  try {
    const img = await loadHtmlImage(file);
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    if (!w || !h) return { file, resized: false };

    const scale = Math.min(1, maxEdge / Math.max(w, h));
    const nw = Math.max(1, Math.round(w * scale));
    const nh = Math.max(1, Math.round(h * scale));

    const canvas = document.createElement('canvas');
    canvas.width = nw;
    canvas.height = nh;
    const ctx = canvas.getContext('2d');
    if (!ctx) return { file, resized: false };
    ctx.drawImage(img, 0, 0, nw, nh);

    const outType = opts.always || file.type === 'image/png' ? 'image/jpeg' : file.type;
    const blob = await canvasToBlob(canvas, outType, opts.quality ?? 0.85);
    if (!blob) return { file, resized: false };
    const out = new File([blob], file.name, { type: outType, lastModified: file.lastModified });
    return { file: out, resized: true };
  } catch {
    return { file, resized: false };
  }
}
