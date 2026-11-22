// Licensed pharmacies by city. The position goes in the body of one request (never in a URL),
// is used for that answer and is not kept by the app or the server.
import { API_URL, ApiError } from '@/api/client';

export type Pharmacy = {
  name: string;
  phone: string | null;
  address: string;
  city: string | null;
  region: string | null;
  short_code: string | null;
  precision: string;
  source_ref: string;
  fetched_at: string | null;
  trust: string;
};

export type CityPharmacies = {
  city_key: string;
  city: string;
  region: string | null;
  distance_km: number | null;
  shown: number;
  total: number;
  pharmacies: Pharmacy[];
};

export type Nearby = {
  radius_km: number;
  precision: string;
  cities: CityPharmacies[];
  nearest_outside: CityPharmacies | null;
  pharmacies_without_a_city: number;
  pharmacies_in_cities_without_a_point: number;
  note: string;
};

export type CityChoice = { city_key: string; city: string; region: string | null; pharmacies: number; located: boolean };

export type PharmacyList = { total: number; count: number; results: Pharmacy[]; note: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}) },
    });
  } catch (error) {
    throw new ApiError('network', null, error instanceof Error ? error.message.slice(0, 160) : '');
  }
  if (!response.ok) throw new ApiError(`http ${response.status}`, response.status);
  return (await response.json()) as T;
}

export const getNearby = (latitude: number, longitude: number, radiusKm = 40, signal?: AbortSignal) =>
  request<Nearby>('/v1/pharmacies/nearby', {
    method: 'POST',
    body: JSON.stringify({ latitude, longitude, radius_km: radiusKm, per_city: 15 }),
    signal,
  });

export const getCities = (signal?: AbortSignal) =>
  request<{ cities: CityChoice[]; note: string }>('/v1/pharmacies/cities', { signal });

export const getCityPharmacies = (cityKey: string, signal?: AbortSignal) =>
  request<PharmacyList>(`/v1/pharmacies?city=${encodeURIComponent(cityKey)}&limit=100`, { signal });

/** A search in the phone's own maps app: the list has no coordinates for a pharmacy. */
export function mapsSearchUrl(pharmacy: Pharmacy): string {
  const query = `${pharmacy.name} ${pharmacy.city ?? ''}`.trim();
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

export function arabicPharmacyError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 503) return 'هذي الخدمة غير مفعّلة على السيرفر للحين';
    if (error.status === null) return 'ما قدرت أوصل للسيرفر';
  }
  return 'صار خطأ. جرّب مرة ثانية';
}
