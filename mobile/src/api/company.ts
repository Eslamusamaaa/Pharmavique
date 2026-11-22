// Company views (market map, thin strengths and forms, radar) and the operator's quality board.
// Registry facts only: no sales or demand numbers exist in the data, and the screens say so.
import { AuthError } from '@/api/auth';
import { ApiError } from '@/api/client';
import { authed } from '@/api/me';

export type CountItem = { name: string; count: number };
export type PriceRange = {
  currency_code: string | null;
  currency_basis: string;
  count: number;
  lowest: string;
  highest: string;
};
export type MarketGroup = {
  ingredients: string[];
  listed: number;
  withdrawn: number;
  makers: number;
  forms: CountItem[];
  strengths: CountItem[];
  price_ranges: PriceRange[];
};
export type MarketMap = {
  ingredient: string;
  listed: number;
  withdrawn: number;
  makers: number;
  top_makers: CountItem[];
  groups: MarketGroup[];
  note: string;
};
export type GapCell = {
  ingredients: string[];
  strength: string;
  dosage_form: string;
  products: number;
  makers: number;
  thin: boolean;
};
export type MissingCell = { ingredients: string[]; strength: string; dosage_form: string };
export type Gaps = { ingredient: string; thin_at: number; cells: GapCell[]; missing: MissingCell[]; note: string };
export type RadarItem = {
  kind: 'added' | 'relisted' | 'withdrawn' | 'price_changed';
  register_number: string;
  trade_name_en: string | null;
  trade_name_ar: string | null;
  marketing_company: string | null;
  ingredients: string[];
  occurred_at: string;
  old_price: string | null;
  new_price: string | null;
  currency_code: string | null;
  currency_basis: string | null;
};
export type Radar = { ingredient: string | null; days: number; count: number; items: RadarItem[]; note: string };

export const getMarketMap = (ingredient: string, signal?: AbortSignal) =>
  authed<MarketMap>('GET', `/v1/company/market?ingredient=${encodeURIComponent(ingredient)}`, undefined, signal);
export const getGaps = (ingredient: string, signal?: AbortSignal) =>
  authed<Gaps>('GET', `/v1/company/gaps?ingredient=${encodeURIComponent(ingredient)}`, undefined, signal);
export const getRadar = (ingredient: string | null, days: number, signal?: AbortSignal) =>
  authed<Radar>(
    'GET',
    `/v1/company/radar?days=${days}${ingredient ? `&ingredient=${encodeURIComponent(ingredient)}` : ''}`,
    undefined,
    signal,
  );

export type ListQuality = {
  list_name: string;
  rows: number;
  linked_matched: number;
  linked_possible: number;
  unlinked: number;
  last_fetched_at: string | null;
};
export type Quality = {
  market: string;
  generated_at: string;
  catalog: {
    products: number;
    listed: number;
    withdrawn: number;
    listed_without_price: number;
    listed_without_ingredients: number;
    listed_with_missing_strength: number;
    listed_without_manufacturer: number;
    listed_with_real_picture: number;
    listed_with_generated_picture: number;
    listed_without_picture: number;
    lists: ListQuality[];
  };
  refresh: {
    available: boolean;
    last_day: string | null;
    days_since_last: number | null;
    overdue: boolean | null;
    days: {
      day: string;
      steps: { name: string; exit_code: number; minutes: number; failed: boolean }[];
      failed_steps: string[];
      load: { loaded: number | null; skipped: number | null; rejected: number | null } | null;
    }[];
  };
  analytics: { products: number; built_at: string | null; first_built_at: string | null; events_7d: number } | null;
  notes: string[];
};

export const getQuality = (signal?: AbortSignal) => authed<Quality>('GET', '/v1/operator/quality', undefined, signal);

export function arabicCompanyError(error: unknown): string {
  if (error instanceof AuthError) return 'سجّل الدخول أول';
  if (error instanceof ApiError) {
    if (error.status === 403) return 'حسابك غير مسموح له بهذي الشاشة';
    if (error.status === 422) return 'اكتب اسم مادة فعالة (حرفين على الأقل)';
    if (error.status === 503) return 'هذي الخدمة غير مفعّلة على السيرفر للحين';
    if (error.status === null) return 'ما قدرت أوصل للسيرفر';
  }
  return 'صار خطأ. جرّب مرة ثانية';
}
