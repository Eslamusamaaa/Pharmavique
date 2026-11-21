// Who is using the app: patient, pharmacist, or a pharma company or drug warehouse owner.
// Chosen on first launch and kept on this device only. There is no sign-in yet, so this changes how
// the app speaks and what it suggests, never what a person is allowed to see.
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

import type { Level } from '@/api/client';

export type Role = 'patient' | 'pharmacist' | 'company';

export const ROLES: { key: Role; label: string; hint: string; level: Level; greeting: string; suggestions: string[] }[] = [
  {
    key: 'patient',
    label: 'مريض',
    hint: 'أبحث عن دوائي وأفهم بياناته',
    level: 'patient',
    greeting: 'عن أي دواء تريد أن تعرف؟',
    suggestions: ['ما سعر بانادول 500؟', 'ما المواد الفعالة في بانادول اكسترا؟', 'هل فيه بديل بنفس المادة؟'],
  },
  {
    key: 'pharmacist',
    label: 'صيدلي',
    hint: 'أبحث عن الدواء وبدائله بسرعة',
    level: 'pharmacist',
    greeting: 'ابحث عن الدواء وبدائله',
    suggestions: ['ما بدائل كونكور بنفس المادة والتركيز؟', 'ما الحالة النظامية لبانادول 500؟', 'هل فيه نشرة سلامة لهذا الدواء؟'],
  },
  {
    key: 'company',
    label: 'صاحب شركة أو مخزن أدوية',
    hint: 'أتابع المنتجات والمنافسين في السوق',
    level: 'clinical',
    greeting: 'استكشف الأدوية في السوق',
    suggestions: ['ما المنتجات التي تحتوي على باراسيتامول؟', 'من الشركة المسوقة لكونكور؟', 'هل فيه نقص مسجل لهذا الدواء؟'],
  },
];

export const roleInfo = (role: Role) => ROLES.find((r) => r.key === role) ?? ROLES[0];

const KEY = 'pharmavique.role.v1';
const listeners = new Set<(r: Role | null) => void>();
let cache: Role | null | undefined;

async function load(): Promise<Role | null> {
  if (cache !== undefined) return cache;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    cache = ROLES.some((r) => r.key === raw) ? (raw as Role) : null;
  } catch {
    cache = null;
  }
  return cache;
}

export async function saveRole(role: Role) {
  cache = role;
  listeners.forEach((l) => l(role));
  try {
    await AsyncStorage.setItem(KEY, role);
  } catch {
    // storage is a convenience: the app works without it
  }
}

/** `ready` turns true once the saved choice has been read; `role` is null until one is made. */
export function useRole() {
  const [role, setRole] = useState<Role | null>(cache ?? null);
  const [ready, setReady] = useState(cache !== undefined);
  useEffect(() => {
    let alive = true;
    load().then((r) => {
      if (!alive) return;
      setRole(r);
      setReady(true);
    });
    const listener = (r: Role | null) => setRole(r);
    listeners.add(listener);
    return () => {
      alive = false;
      listeners.delete(listener);
    };
  }, []);
  return { role, ready, setRole: useCallback(saveRole, []) };
}
