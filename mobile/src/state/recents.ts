// Recent searches, kept on this device only (never sent anywhere).
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

export type Recent = { ar: string; en: string | null; register: string | null; query: string };

const KEY = 'pharmavique.recents.v1';
const MAX = 8;
const listeners = new Set<(r: Recent[]) => void>();
let cache: Recent[] | null = null;

async function load(): Promise<Recent[]> {
  if (cache) return cache;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    cache = raw ? (JSON.parse(raw) as Recent[]) : [];
  } catch {
    cache = [];
  }
  return cache;
}

async function save(next: Recent[]) {
  cache = next;
  listeners.forEach((l) => l(next));
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage is a convenience: the app works without it
  }
}

export async function addRecent(item: Recent) {
  const current = await load();
  const id = item.register ?? item.query;
  const rest = current.filter((r) => (r.register ?? r.query) !== id);
  await save([item, ...rest].slice(0, MAX));
}

export async function removeRecent(item: Recent) {
  const current = await load();
  const id = item.register ?? item.query;
  await save(current.filter((r) => (r.register ?? r.query) !== id));
}

export async function clearRecents() {
  await save([]);
}

export function useRecents(): Recent[] {
  const [items, setItems] = useState<Recent[]>(cache ?? []);
  useEffect(() => {
    let alive = true;
    load().then((r) => alive && setItems(r));
    const listener = (r: Recent[]) => setItems(r);
    listeners.add(listener);
    return () => {
      alive = false;
      listeners.delete(listener);
    };
  }, []);
  return items;
}

export function useRecentActions() {
  return {
    add: useCallback(addRecent, []),
    remove: useCallback(removeRecent, []),
    clear: useCallback(clearRecents, []),
  };
}
