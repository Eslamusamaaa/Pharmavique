// Thin client for the Pharmavique API. The app holds no drug data of its own.
// The address comes from EXPO_PUBLIC_API_URL. On a phone it must be the computer's LAN address
// (for example http://192.168.1.10:8000), not 127.0.0.1.

export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');

export type Product = {
  market: string;
  register_number: string;
  trade_name_en: string | null;
  trade_name_ar: string | null;
  ingredients: string[];
  dosage_form_en: string | null;
  dosage_form_ar: string | null;
  marketing_company: string | null;
  listing_status: string;
  legal_status: string | null;
};

export type SearchHit = Product & {
  score: number;
  exact: boolean;
  reasons: { signal: string; rank: number; score: number }[];
};

export type SearchResult = { query: string; count: number; results: SearchHit[]; disclaimer: string };

export type Ingredient = { name: string; strength: string | null; unit: string | null };
export type Price = { amount: string; currency_code: string | null; currency_basis: string };

export type DrugPage = Omit<Product, 'ingredients'> & {
  ingredients: Ingredient[];
  route_en: string | null;
  route_ar: string | null;
  package_type: string | null;
  package_size: number | null;
  shelf_life: string | null;
  storage_en: string | null;
  storage_ar: string | null;
  distribution_site: string | null;
  atc_codes: string[];
  authorization_status: string | null;
  marketing_status: string | null;
  marketing_company_country: string | null;
  manufacturers: { name: string; country: string | null }[];
  price: Price | null;
  provenance: { source: string | null; source_ref: string | null; fetched_at: string | null; trust: string | null };
  disclaimer: string;
};

export type Verdict = 'equivalent' | 'possible_needs_pharmacist_check' | 'not_equivalent';

export type SameIngredient = {
  register_number: string;
  trade_name_en: string | null;
  trade_name_ar: string | null;
  ingredients: Ingredient[];
  dosage_form_en: string | null;
  dosage_form_ar: string | null;
  marketing_company: string | null;
  price: Price | null;
  verdict: Verdict;
  strength: string;
  form_family: string;
};

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { signal, headers: { Accept: 'application/json' } });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError('network', null);
  }
  if (!response.ok) throw new ApiError(`http ${response.status}`, response.status);
  return (await response.json()) as T;
}

export function searchDrugs(q: string, signal?: AbortSignal, limit = 20): Promise<SearchResult> {
  const params = new URLSearchParams({ q, limit: String(limit) });
  return getJson<SearchResult>(`/v1/search?${params.toString()}`, signal);
}

export function getDrugPage(registerNumber: string, signal?: AbortSignal): Promise<DrugPage> {
  return getJson<DrugPage>(`/v1/products/${encodeURIComponent(registerNumber)}/details`, signal);
}

export function getSameIngredient(
  registerNumber: string,
  signal?: AbortSignal,
): Promise<{ count: number; results: SameIngredient[] }> {
  return getJson(`/v1/products/${encodeURIComponent(registerNumber)}/same-ingredient?limit=30`, signal);
}

export function displayName(p: { trade_name_ar: string | null; trade_name_en: string | null; register_number: string }) {
  return p.trade_name_ar || p.trade_name_en || p.register_number;
}

/** Plain lowercase text without Arabic diacritics or tatweel, for factual "matched on" hints. */
export function fold(text: string): string {
  return text
    .toLowerCase()
    .replace(/[ً-ْـ]/g, '')
    .replace(/[إأآ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .trim();
}

export function friendlyError(e: unknown): string {
  const status = e instanceof ApiError ? e.status : null;
  if (status === null) return 'مش قادر أوصل للسيرفر. اتأكد إن الـ API شغال وإن الموبايل على نفس الشبكة.';
  if (status === 404) return 'الدواء ده مش موجود في السجل.';
  return `السيرفر رد بخطأ (${status}).`;
}
