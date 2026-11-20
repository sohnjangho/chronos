import { isRouter, type ModelInfo } from './model';

/** 업체 차례: Liner 먼저, 그다음 anthropic · openai · google, 나머지는 업체 이름 차례. */
const VENDOR_ORDER = ['liner', 'anthropic', 'openai', 'google'];
/** 「Liner 라우터만」의 추천 차례: 라우터 셋, 그다음 liner-mark. */
const RECOMMENDED = ['liner-claude-router', 'liner-gpt-router', 'liner-gemini-router', 'liner-mark'];

/** "Google: Gemini 4 Neon" → "Gemini 4 Neon". 앞이 업체 이름일 때만 뗀다. */
export function shortName(m: ModelInfo): string {
  const prefix = `${m.vendor_name}:`;
  return m.name.startsWith(prefix) ? m.name.slice(prefix.length).trim() : m.name;
}

/** 문맥 길이: 1048576 → "1.05M", 200000 → "200K". 모르면 "". */
export function contextText(n: number | null): string {
  if (n === null) return '';
  if (n >= 1_000_000) return `${parseFloat((n / 1_000_000).toFixed(2))}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

/** 고르기 칸의 글: "Gemini 4 Neon · 1.05M". */
export function modelLabel(m: ModelInfo): string {
  const ctx = contextText(m.context_length);
  return ctx ? `${shortName(m)} · ${ctx}` : shortName(m);
}

export interface VendorGroup {
  vendor: string;
  vendor_name: string;
  models: ModelInfo[];
}

function vendorRank(a: VendorGroup, b: VendorGroup): number {
  const rank = (g: VendorGroup) => (VENDOR_ORDER.includes(g.vendor) ? VENDOR_ORDER.indexOf(g.vendor) : VENDOR_ORDER.length);
  return rank(a) - rank(b) || a.vendor_name.localeCompare(b.vendor_name);
}

/** 업체별로 묶는다. 묶음 안의 차례는 받은 차례. */
export function groupByVendor(models: ModelInfo[]): VendorGroup[] {
  const groups = new Map<string, VendorGroup>();
  for (const m of models) {
    const g = groups.get(m.vendor) ?? { vendor: m.vendor, vendor_name: m.vendor_name, models: [] };
    g.models.push(m);
    groups.set(m.vendor, g);
  }
  return [...groups.values()].sort(vendorRank);
}

/** 모델 고르기 거르개. minContext 0 은 전체. */
export interface ModelFilter {
  query: string;
  vendors: string[];
  minContext: number;
  chatOnly: boolean;
  linerRouters: boolean;
}

export const DEFAULT_FILTER: ModelFilter = { query: '', vendors: [], minContext: 0, chatOnly: true, linerRouters: false };

export const isDefaultFilter = (f: ModelFilter) =>
  f.query === '' && f.vendors.length === 0 && f.minContext === 0 && f.chatOnly && !f.linerRouters;

const isRecommended = (m: ModelInfo) => m.vendor === 'liner' && (isRouter(m.id) || m.id === 'liner-mark');

function recommendedFirst(models: ModelInfo[]): ModelInfo[] {
  const rank = (m: ModelInfo) => (RECOMMENDED.includes(m.id) ? RECOMMENDED.indexOf(m.id) : RECOMMENDED.length);
  return [...models].sort((a, b) => rank(a) - rank(b));
}

/** 찾기(이름·id·업체 이름, 대소문자 무시)와 거르개를 함께 건다. ignoreVendors 는 업체 수를 셀 때 쓴다. */
export function filterModels(models: ModelInfo[], f: ModelFilter, ignoreVendors = false): ModelInfo[] {
  const q = f.query.trim().toLowerCase();
  const kept = models.filter(
    (m) =>
      (!f.chatOnly || m.chat) &&
      (ignoreVendors || f.vendors.length === 0 || f.vendors.includes(m.vendor)) &&
      (f.minContext === 0 || (m.context_length ?? 0) >= f.minContext) &&
      (!f.linerRouters || isRecommended(m)) &&
      (!q || [m.name, m.id, m.vendor_name].some((t) => t.toLowerCase().includes(q))),
  );
  return f.linerRouters ? recommendedFirst(kept) : kept;
}

/** 업체 고르기에 보일 업체와 수(다른 거르개를 건 뒤의 수). 고른 업체는 0 이어도 남긴다. */
export function vendorFacets(models: ModelInfo[], f: ModelFilter): { vendor: string; vendor_name: string; count: number }[] {
  const counted = new Map(groupByVendor(filterModels(models, f, true)).map((g) => [g.vendor, g.models.length]));
  return groupByVendor(models)
    .map((g) => ({ vendor: g.vendor, vendor_name: g.vendor_name, count: counted.get(g.vendor) ?? 0 }))
    .filter((g) => g.count > 0 || f.vendors.includes(g.vendor));
}
