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
};

export type SearchHit = Product & {
  score: number;
  exact: boolean;
  reasons: { signal: string; rank: number; score: number }[];
};

export type SearchResult = {
  query: string;
  count: number;
  results: SearchHit[];
  disclaimer: string;
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

export function getDrug(registerNumber: string, signal?: AbortSignal): Promise<Product> {
  return getJson<Product>(`/v1/products/${encodeURIComponent(registerNumber)}`, signal);
}

export function displayName(p: Product): string {
  return p.trade_name_ar || p.trade_name_en || p.register_number;
}
