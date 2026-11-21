// Accounts: sign up, sign in, keep the session fresh, sign out, delete the account.
// The refresh token lives in the device's secure storage (Keychain or Keystore), never in plain
// storage. The short-lived access token stays in memory and is renewed with the refresh token.
import * as SecureStore from 'expo-secure-store';

import { API_URL } from '@/api/client';

export type AccountRole = 'patient' | 'pharmacist' | 'company' | 'operator';

export type Account = { id: string; email: string; role: AccountRole; tenant_id: string | null };

type SessionBody = { access_token: string; refresh_token: string; expires_in: number; user: Account };

export class AuthError extends Error {
  constructor(
    public kind: 'wrong_login' | 'email_taken' | 'invalid' | 'unavailable' | 'network' | 'expired' | 'unknown',
    public detail?: string,
  ) {
    super(kind);
  }
}

const REFRESH_KEY = 'pharmavique.refresh.v1';
const SKEW_MS = 30_000; // renew a little before the token really expires

let access: { token: string; expiresAt: number } | null = null;
let current: Account | null | undefined; // undefined: not read from storage yet
const listeners = new Set<(a: Account | null) => void>();

function publish(account: Account | null) {
  current = account;
  listeners.forEach((l) => l(account));
}

export function subscribe(listener: (a: Account | null) => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

async function readRefresh(): Promise<string | null> {
  try {
    return await SecureStore.getItemAsync(REFRESH_KEY);
  } catch {
    return null;
  }
}

async function saveRefresh(token: string | null): Promise<void> {
  try {
    if (token) await SecureStore.setItemAsync(REFRESH_KEY, token);
    else await SecureStore.deleteItemAsync(REFRESH_KEY);
  } catch {
    // secure storage unavailable: the session then lasts until the app is closed
  }
}

async function post(path: string, body: unknown, token?: string): Promise<Response> {
  try {
    return await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body),
    });
  } catch {
    throw new AuthError('network');
  }
}

async function readError(response: Response): Promise<string | undefined> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === 'string' ? body.detail : undefined;
  } catch {
    return undefined;
  }
}

async function adopt(response: Response): Promise<Account> {
  if (!response.ok) {
    const detail = await readError(response);
    if (response.status === 401) throw new AuthError('wrong_login', detail);
    if (response.status === 409) throw new AuthError('email_taken', detail);
    if (response.status === 422) throw new AuthError('invalid', detail);
    if (response.status === 503) throw new AuthError('unavailable', detail);
    throw new AuthError('unknown', detail);
  }
  const session = (await response.json()) as SessionBody;
  access = { token: session.access_token, expiresAt: Date.now() + session.expires_in * 1000 - SKEW_MS };
  await saveRefresh(session.refresh_token);
  publish(session.user);
  return session.user;
}

export async function signUp(email: string, password: string, role: Exclude<AccountRole, 'operator'>): Promise<Account> {
  return adopt(await post('/v1/auth/register', { email, password, role }));
}

export async function signIn(email: string, password: string): Promise<Account> {
  return adopt(await post('/v1/auth/login', { email, password }));
}

/** Restore the account from the stored refresh token when the app opens. */
export async function restore(): Promise<Account | null> {
  if (current !== undefined) return current;
  const refresh = await readRefresh();
  if (!refresh) {
    publish(null);
    return null;
  }
  try {
    return await adopt(await post('/v1/auth/refresh', { refresh_token: refresh }));
  } catch (error) {
    if (error instanceof AuthError && error.kind === 'network') {
      current = null; // offline: stay signed out for now, keep the stored token for the next start
      return null;
    }
    await saveRefresh(null);
    publish(null);
    return null;
  }
}

export async function signOut(): Promise<void> {
  const refresh = await readRefresh();
  access = null;
  await saveRefresh(null);
  publish(null);
  if (refresh) await post('/v1/auth/logout', { refresh_token: refresh }).catch(() => undefined);
}

/** A valid access token, renewed first when it is about to expire. Null when signed out. */
export async function accessToken(): Promise<string | null> {
  if (access && Date.now() < access.expiresAt) return access.token;
  const refresh = await readRefresh();
  if (!refresh) return null;
  try {
    await adopt(await post('/v1/auth/refresh', { refresh_token: refresh }));
  } catch {
    return null;
  }
  return access?.token ?? null;
}

export async function deleteAccount(): Promise<void> {
  const token = await accessToken();
  if (!token) throw new AuthError('expired');
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/auth/me`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw new AuthError('network');
  }
  if (!response.ok) throw new AuthError('unknown', await readError(response));
  access = null;
  await saveRefresh(null);
  publish(null);
}

export function arabicAuthError(error: unknown): string {
  if (!(error instanceof AuthError)) return 'حصلت مشكلة. جرّب تاني.';
  switch (error.kind) {
    case 'wrong_login':
      return 'الإيميل أو كلمة المرور غلط';
    case 'email_taken':
      return 'الإيميل ده عليه حساب بالفعل. جرّب تسجيل الدخول';
    case 'invalid':
      return 'اكتب إيميل صحيح وكلمة مرور من 10 حروف على الأقل';
    case 'unavailable':
      return 'الحسابات مش متفعلة على السيرفر لسه';
    case 'network':
      return 'مش قادر أوصل للسيرفر. اتأكد من النت';
    case 'expired':
      return 'الجلسة انتهت. سجّل الدخول تاني';
    default:
      return 'حصلت مشكلة. جرّب تاني.';
  }
}
