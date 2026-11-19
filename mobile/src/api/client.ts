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

// ---- assistant, voice and scan --------------------------------------------------------------
export type Level = 'patient' | 'pharmacist' | 'clinical';

export type AssistantCitation = {
  number: number;
  source_id: string;
  title: string;
  url: string | null;
  kind: 'catalog' | 'document' | string;
  published: string | null;
};

export type AssistantAnswer = {
  answer: string;
  citations: AssistantCitation[];
  grounded: boolean;
  general: boolean;
  urgent: boolean;
  refused: boolean;
  level: Level;
  tools_used: string[];
  disclaimer: string;
};

export type ScanCandidate = {
  register_number: string;
  trade_name_ar: string | null;
  trade_name_en: string | null;
  score: number;
};

export type ScanLine = {
  raw_text: string;
  name: string;
  strength: string | null;
  form: string | null;
  dose: string | null;
  needs_review: boolean;
  candidates: ScanCandidate[];
};

export type ScanResult = { kind: 'box' | 'prescription'; status: 'needs_review' | 'nothing_read'; lines: ScanLine[] };

async function postJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError('network', null);
  }
  if (!response.ok) throw new ApiError(`http ${response.status}`, response.status);
  return (await response.json()) as T;
}

/** A file picked or recorded on the device, as multipart form data (native and web). */
async function fileField(uri: string, name: string, type: string): Promise<Blob | { uri: string; name: string; type: string }> {
  if (uri.startsWith('blob:') || uri.startsWith('data:') || uri.startsWith('http')) {
    return await (await fetch(uri)).blob();
  }
  return { uri, name, type };
}

async function postFile<T>(path: string, field: string, uri: string, name: string, type: string): Promise<T> {
  const form = new FormData();
  const file = await fileField(uri, name, type);
  if (file instanceof Blob) form.append(field, file, name);
  else form.append(field, file as unknown as Blob);
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { method: 'POST', body: form, headers: { Accept: 'application/json' } });
  } catch {
    throw new ApiError('network', null);
  }
  if (!response.ok) throw new ApiError(`http ${response.status}`, response.status);
  return (await response.json()) as T;
}

export type ConversationTurn = { role: 'user' | 'assistant'; text: string };

export function askAssistant(
  body: {
    question: string;
    level: Level;
    register_number?: string | null;
    spoken?: boolean;
    history?: ConversationTurn[]; // earlier turns, oldest first: the server keeps no conversation
  },
  signal?: AbortSignal,
): Promise<AssistantAnswer> {
  return postJson<AssistantAnswer>('/v1/assistant/ask', body, signal);
}

export function transcribeAudio(uri: string): Promise<{ text: string }> {
  const name = uri.endsWith('.webm') ? 'question.webm' : 'question.m4a';
  return postFile('/v1/voice/transcribe', 'audio', uri, name, name.endsWith('webm') ? 'audio/webm' : 'audio/m4a');
}

/** A one-time link to the spoken text (Saudi Arabic voice), ready for the audio player. */
export async function speakLink(text: string): Promise<string> {
  const { url } = await postJson<{ url: string; media_type: string }>('/v1/voice/speak', { text, as_link: true });
  return `${API_URL}${url}`;
}

export function scanImage(uri: string, mimeType: string, kind: 'box' | 'prescription'): Promise<ScanResult> {
  const name = mimeType === 'image/png' ? 'scan.png' : mimeType === 'image/webp' ? 'scan.webp' : 'scan.jpg';
  return postFile(`/v1/recognition/scan?kind=${kind}`, 'image', uri, name, mimeType);
}
