import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ScrollView, StyleSheet, Text } from 'react-native';

import { ApiError, displayName, getDrug, type Product } from '@/api/client';
import { Badge, Card, Disclaimer, Loading, Message, Row, Title } from '@/components/ui';
import { colors } from '@/theme';

type State = { kind: 'loading' } | { kind: 'done'; drug: Product } | { kind: 'error'; title: string };

export default function Drug() {
  const { register } = useLocalSearchParams<{ register: string }>();
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    getDrug(register, controller.signal)
      .then((drug) => setState({ kind: 'done', drug }))
      .catch((e: unknown) => {
        if ((e as Error).name === 'AbortError') return;
        const status = e instanceof ApiError ? e.status : null;
        setState({
          kind: 'error',
          title: status === 404 ? 'الدواء ده مش موجود في السجل' : 'مش قادر أجيب بيانات الدواء',
        });
      });
    return () => controller.abort();
  }, [register]);

  if (state.kind === 'loading') return <Loading />;
  if (state.kind === 'error') return <Message title={state.title} />;

  const d = state.drug;
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Card>
        <Title>{displayName(d)}</Title>
        {d.trade_name_en ? <Text style={styles.latin}>{d.trade_name_en}</Text> : null}
        {d.listing_status === 'listed' ? (
          <Badge label="مدرج في السجل" tone="ok" />
        ) : (
          <Badge label="غير مدرج حالياً" tone="danger" />
        )}
      </Card>
      <Card>
        <Row label="المادة الفعالة" value={d.ingredients.join(' + ')} />
        <Row label="الشكل الصيدلاني" value={d.dosage_form_ar ?? d.dosage_form_en} />
        <Row label="الشركة" value={d.marketing_company} />
        <Row label="رقم التسجيل" value={d.register_number} />
        <Row label="المصدر" value="SFDA — سجل الأدوية الرسمي" />
      </Card>
      <Disclaimer />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 12 },
  latin: { fontSize: 14, color: colors.ink2, textAlign: 'left' },
});
