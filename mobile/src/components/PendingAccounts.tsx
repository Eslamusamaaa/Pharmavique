// The operator's list of pharmacist and company accounts waiting to be verified (ADR-020). Verifying
// or rejecting emails the person; a rejected account keeps working, only without the badge.
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { arabicCompanyError, getPendingAccounts, reviewAccount, type PendingAccount } from '@/api/company';
import { Card, H2, Pill, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

const ROLE_AR: Record<string, string> = { pharmacist: 'صيدلي', company: 'شركة' };

export function PendingAccounts() {
  const { c } = useTheme();
  const [accounts, setAccounts] = useState<PendingAccount[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setAccounts((await getPendingAccounts()).accounts);
      setError(null);
    } catch (e) {
      setError(arabicCompanyError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (id: string, decision: 'verified' | 'rejected') => {
    setBusy(id);
    try {
      await reviewAccount(id, decision);
      setAccounts((all) => (all ?? []).filter((a) => a.id !== id));
    } catch (e) {
      setError(arabicCompanyError(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={{ gap: 8 }}>
      <H2>حسابات تنتظر التوثيق</H2>
      {error ? (
        <T size={14} color={c.rd}>
          {error}
        </T>
      ) : null}
      {accounts === null && !error ? <T size={14} color={c.ink2}>نجيب القائمة…</T> : null}
      {accounts?.length === 0 ? <Pill tone="ok" label="ما فيه حسابات تنتظر" /> : null}
      {accounts?.map((a) => (
        <Card key={a.id} style={{ gap: 8 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <T weight={700} latin style={{ flex: 1 }}>
              {a.email}
            </T>
            <Pill label={ROLE_AR[a.role] ?? a.role} />
          </Row>
          <Row gap={8}>
            <Pressable
              disabled={busy === a.id}
              onPress={() => decide(a.id, 'verified')}
              style={[styles.button, { backgroundColor: c.pr, opacity: busy === a.id ? 0.5 : 1 }]}
              accessibilityRole="button"
            >
              <T weight={700} color={c.prt}>
                وثّق
              </T>
            </Pressable>
            <Pressable
              disabled={busy === a.id}
              onPress={() => decide(a.id, 'rejected')}
              style={[styles.button, { borderColor: c.rd, borderWidth: 1.5, opacity: busy === a.id ? 0.5 : 1 }]}
              accessibilityRole="button"
            >
              <T weight={600} color={c.rd}>
                ارفض
              </T>
            </Pressable>
          </Row>
        </Card>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  button: { flex: 1, minHeight: 44, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
