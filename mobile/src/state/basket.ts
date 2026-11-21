// "My medicines": the products a person added to check against each other, kept on this device
// only (health data is never sent anywhere except the interaction check itself).
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useEffect, useState } from 'react';

export type BasketItem = { register: string; ar: string | null; en: string | null };

const KEY = 'pharmavique.my-medicines.v1';
export const MAX_ITEMS = 12;
const listeners = new Set<(items: BasketItem[]) => void>();
let cache: BasketItem[] | null = null;

async function load(): Promise<BasketItem[]> {
  if (cache) return cache;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    cache = raw ? (JSON.parse(raw) as BasketItem[]) : [];
  } catch {
    cache = [];
  }
  return cache;
}

async function save(next: BasketItem[]) {
  cache = next;
  listeners.forEach((l) => l(next));
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // storage is a convenience: the list still works for this session
  }
}

/** The saved list (`ready` once read) and the ways to change it. */
export function useSavedBasket() {
  const [items, setItems] = useState<BasketItem[]>(cache ?? []);
  const [ready, setReady] = useState(cache !== null);
  useEffect(() => {
    let alive = true;
    load().then((v) => {
      if (!alive) return;
      setItems(v);
      setReady(true);
    });
    listeners.add(setItems);
    return () => {
      alive = false;
      listeners.delete(setItems);
    };
  }, []);
  const set = useCallback((next: BasketItem[]) => save(next.slice(0, MAX_ITEMS)), []);
  return { items, ready, set };
}
