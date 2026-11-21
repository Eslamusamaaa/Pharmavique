// Interaction check for the pharmacist: nothing is saved. It can start with the medicines of a
// scanned prescription (passed as a short JSON list), so a whole prescription is checked at once.
import { useLocalSearchParams } from 'expo-router';
import { useMemo } from 'react';

import { InteractionBasket } from '@/components/InteractionBasket';
import { MAX_ITEMS, type BasketItem } from '@/state/basket';

function parseItems(raw: string | undefined): BasketItem[] {
  if (!raw) return [];
  try {
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    return value
      .filter((i): i is BasketItem => typeof i === 'object' && i !== null && typeof (i as BasketItem).register === 'string')
      .map((i) => ({ register: i.register, ar: i.ar ?? null, en: i.en ?? null }))
      .slice(0, MAX_ITEMS);
  } catch {
    return [];
  }
}

export default function Interactions() {
  const { items } = useLocalSearchParams<{ items?: string }>();
  const initial = useMemo(() => parseItems(items), [items]);
  return (
    <InteractionBasket
      title="فحص التداخل بين الأدوية"
      intro="أضف دوائين أو أكثر لترى التداخلات المسجّلة في المصدر بينها والمواد الفعالة المكررة."
      persist={false}
      initialItems={initial}
    />
  );
}
