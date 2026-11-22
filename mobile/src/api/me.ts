// The signed-in person's saved medicines, allergies, alerts and digest. Every call carries the access
// token; the API also limits every query to this person's rows.
import { accessToken, AuthError } from '@/api/auth';
import {
  API_URL,
  ApiError,
  postFile,
  type AssistantAnswer,
  type ConversationTurn,
  type Level,
  type Product,
  type ScanResult,
} from '@/api/client';

export type AllergyMatch = { allergy: string; ingredient: string };

export type MedicineStatus = 'current' | 'past';

export type SavedMedicine = {
  register_number: string;
  added_at: string;
  status: MedicineStatus; // the person's own record: taken now, or taken before
  status_changed_at: string | null;
  product: Product | null;
  allergy_matches: AllergyMatch[];
};

export type SavedMedicines = { count: number; items: SavedMedicine[]; allergy_note: string };

export type AlertItem = {
  id: string;
  kind: 'price_changed' | 'withdrawn' | 'relisted';
  register_number: string;
  product: Product | null;
  occurred_at: string;
  details: Record<string, string | null>;
  read: boolean;
};

export type Alerts = { unread: number; items: AlertItem[] };

export type Digest = { days: number; counts: Record<string, number>; summary: string; items: AlertItem[] };

export type AllergyCheck = { register_number: string; matches: AllergyMatch[]; checked_allergies: number; note: string };

export async function authed<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const token = await accessToken();
  if (!token) throw new AuthError('expired');
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      signal,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError('network', null, error instanceof Error ? error.message.slice(0, 160) : '');
  }
  if (response.status === 401) throw new AuthError('expired');
  if (!response.ok) {
    let detail = '';
    try {
      const parsed = (await response.json()) as { detail?: unknown };
      if (typeof parsed.detail === 'string') detail = parsed.detail;
    } catch {
      // no body
    }
    throw new ApiError(`http ${response.status}`, response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export const getSaved = (signal?: AbortSignal) => authed<SavedMedicines>('GET', '/v1/me/medicines', undefined, signal);
export const saveMedicine = (register: string) => authed<void>('PUT', `/v1/me/medicines/${encodeURIComponent(register)}`);
export const removeMedicine = (register: string) => authed<void>('DELETE', `/v1/me/medicines/${encodeURIComponent(register)}`);

export const getAllergies = (signal?: AbortSignal) =>
  authed<{ items: { ingredient: string }[]; note: string }>('GET', '/v1/me/allergies', undefined, signal);
export const addAllergy = (ingredient: string) => authed<void>('PUT', '/v1/me/allergies', { ingredient });
export const removeAllergy = (ingredient: string) =>
  authed<void>('DELETE', `/v1/me/allergies?ingredient=${encodeURIComponent(ingredient)}`);
export const getAllergyCheck = (register: string, signal?: AbortSignal) =>
  authed<AllergyCheck>('GET', `/v1/me/allergy-check/${encodeURIComponent(register)}`, undefined, signal);

export const setMedicineStatus = (register: string, status: MedicineStatus) =>
  authed<void>('PUT', `/v1/me/medicines/${encodeURIComponent(register)}/status`, { status });

export type HistoryFinding = {
  kind: 'interaction' | 'duplicate_ingredient';
  severity: string | null; // as the source rates it
  source: string | null;
  with_register_number: string;
  with_name: string;
  ingredients: string[];
  about_register_number: string | null;
};

export type HistoryCheck = {
  register_number: string;
  name: string;
  ingredients: string[];
  already_taken: boolean;
  compared_with: { register_number: string; name: string }[];
  findings: HistoryFinding[];
  allergy_matches: AllergyMatch[];
  unmatched_ingredients: string[];
  complete: boolean;
  note: string;
};

export type CurrentInteractions = {
  medicines: { register_number: string; name: string }[];
  findings: HistoryFinding[];
  complete: boolean;
  note: string;
};

export const getHistoryCheck = (register: string, signal?: AbortSignal) =>
  authed<HistoryCheck>('GET', `/v1/me/history/check/${encodeURIComponent(register)}`, undefined, signal);
export const getCurrentInteractions = (signal?: AbortSignal) =>
  authed<CurrentInteractions>('GET', '/v1/me/history/interactions', undefined, signal);

/** Ask about a drug and compare it with my current medicines. The comparison runs on the server;
 * the language model never sees my medicines. */
export const askWithMyMedicines = (
  body: { question: string; level: Level; register_number: string; spoken?: boolean; history?: ConversationTurn[] },
  signal?: AbortSignal,
) => authed<AssistantAnswer>('POST', '/v1/assistant/ask', { ...body, use_history: true }, signal);

export type ShelfItem = { register_number: string; added_at: string; product: Product | null };
export type Shelf = { count: number; items: ShelfItem[]; note: string };

/** Optional features this server has switched on (public). */
export async function getFeatures(signal?: AbortSignal): Promise<{ shelf_scan: boolean }> {
  try {
    const response = await fetch(`${API_URL}/v1/features`, { signal, headers: { Accept: 'application/json' } });
    if (!response.ok) return { shelf_scan: false };
    return (await response.json()) as { shelf_scan: boolean };
  } catch {
    return { shelf_scan: false };
  }
}

/** A photo of a shelf: the boxes it proposes, every one for the pharmacist to confirm. */
export async function scanShelfPhoto(uri: string, mimeType: string): Promise<ScanResult> {
  const token = await accessToken();
  if (!token) throw new AuthError('expired');
  const name = mimeType === 'image/png' ? 'shelf.png' : mimeType === 'image/webp' ? 'shelf.webp' : 'shelf.jpg';
  return postFile<ScanResult>('/v1/recognition/scan?kind=shelf', 'image', uri, name, mimeType, {
    Authorization: `Bearer ${token}`,
  });
}

export const getShelf = (signal?: AbortSignal) => authed<Shelf>('GET', '/v1/me/shelf', undefined, signal);
export const confirmShelf = (registerNumbers: string[]) =>
  authed<{ added: number; already_on_the_shelf: number; unknown: string[] }>('POST', '/v1/me/shelf', {
    register_numbers: registerNumbers,
  });
export const removeFromShelf = (register: string) =>
  authed<void>('DELETE', `/v1/me/shelf/${encodeURIComponent(register)}`);

export const getAlerts = (signal?: AbortSignal) => authed<Alerts>('GET', '/v1/me/alerts', undefined, signal);
export const markAlertsRead = (alertId?: string) =>
  authed<{ marked: number }>('POST', '/v1/me/alerts/read', alertId ? { alert_id: alertId } : {});
export const getDigest = (days = 7, signal?: AbortSignal) =>
  authed<Digest>('GET', `/v1/me/digest?days=${days}`, undefined, signal);

/** Active ingredient names that start with the text (public; no sign-in needed). */
export async function searchIngredients(q: string, signal?: AbortSignal): Promise<string[]> {
  try {
    const response = await fetch(`${API_URL}/v1/ingredients?q=${encodeURIComponent(q)}&limit=8`, {
      signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return [];
    return ((await response.json()) as { items: string[] }).items;
  } catch {
    return [];
  }
}

export function arabicMeError(error: unknown): string {
  if (error instanceof AuthError) return 'سجّل الدخول أول';
  if (error instanceof ApiError) {
    if (error.status === 404) return 'هذا الدواء غير موجود في السجل';
    if (error.status === 422) return 'اختر مادة فعالة من القائمة';
    if (error.status === 503) return 'هذي الخدمة غير مفعّلة على السيرفر للحين';
    if (error.status === null) return 'ما قدرت أوصل للسيرفر';
  }
  return 'صار خطأ. جرّب مرة ثانية';
}
