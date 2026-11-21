// The signed-in account as React state. `account` is null when signed out, undefined while loading.
import { useEffect, useState } from 'react';

import { restore, subscribe, type Account } from '@/api/auth';

export function useAccount(): { account: Account | null | undefined } {
  const [account, setAccount] = useState<Account | null | undefined>(undefined);
  useEffect(() => {
    let alive = true;
    restore().then((a) => alive && setAccount(a));
    const off = subscribe((a) => alive && setAccount(a));
    return () => {
      alive = false;
      off();
    };
  }, []);
  return { account };
}
