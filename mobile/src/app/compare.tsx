// Two drugs side by side. The verdict is computed by the API's rules; this screen only shows it.
import { router, useLocalSearchParams } from 'expo-router';
import { ArrowRightIcon, EqualsIcon, WarningIcon } from 'phosphor-react-native';
import { useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { displayName, friendlyError, getCompare, type Compare, type CompareSide } from '@/api/client';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

type State = { kind: 'loading' } | { kind: 'done'; data: Compare } | { kind: 'error'; detail: string };

const UNIT_AR: Record<string, string> = { mg: 'ملجم', mcg: 'ميكروجرام', g: 'جم', ml: 'مل', iu: 'وحدة دولية' };

function unitAr(unit: string | null): string {
  if (!unit) return '';
  return unit
    .split('/')
    .map((u) => UNIT_AR[u.trim().toLowerCase()] ?? u)
    .join(' / ');
}

function ingredientsText(side: CompareSide): string {
  return side.ingredients.map((i) => `${i.name}${i.strength ? ` ${i.strength} ${unitAr(i.unit)}` : ''}`).join('\n');
}

function priceText(side: CompareSide): string {
  if (!side.price) return 'غير مسجّل';
  const label = side.price.currency_code === 'SAR' ? 'ريال (افتراضي)' : 'العملة غير مذكورة';
  return `${side.price.amount} ${label}`;
}

function listing(side: CompareSide): string {
  return side.listing_status === 'listed' ? 'مدرج' : 'غير مدرج';
}

export default function CompareScreen() {
  const { c } = useTheme();
  const { a, b } = useLocalSearchParams<{ a: string; b: string }>();
  const [state, setState] = useState<State>({ kind: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: 'loading' });
    getCompare(a, b, controller.signal)
      .then((data) => setState({ kind: 'done', data }))
      .catch((e: unknown) => {
        if ((e as Error).name !== 'AbortError') setState({ kind: 'error', detail: friendlyError(e) });
      });
    return () => controller.abort();
  }, [a, b]);

  const header = (
    <View style={styles.topBar}>
      <Pressable
        onPress={() => (router.canGoBack() ? router.back() : router.navigate('/search'))}
        style={styles.iconBtn}
        accessibilityLabel="رجوع"
      >
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        مقارنة دوائين
      </T>
    </View>
  );

  if (state.kind !== 'done') {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <DisclaimerBar />
        {state.kind === 'loading' ? <Loading /> : <Message title="مش قادر أقارن الدوائين" detail={state.detail} />}
      </SafeAreaView>
    );
  }

  const { a: left, b: right, verdict, differences } = state.data;
  const tier =
    verdict === 'equivalent'
      ? { label: 'نفس المادة الفعالة والتركيز والشكل', tone: 'neutral' as const, icon: <EqualsIcon size={14} color={c.pr} weight="fill" /> }
      : verdict === 'possible_needs_pharmacist_check'
        ? { label: 'محتمل ويحتاج مراجعة الصيدلي', tone: 'wn' as const, icon: <WarningIcon size={14} color={c.wn} weight="fill" /> }
        : { label: 'مادة فعالة أو تركيز أو شكل مختلف', tone: 'muted' as const, icon: null };

  const rows: { key: string; label: string; a: string | null; b: string | null }[] = [
    { key: 'ingredients', label: 'المادة الفعالة والتركيز', a: ingredientsText(left), b: ingredientsText(right) },
    { key: 'dosage_form', label: 'الشكل الدوائي', a: left.dosage_form_ar ?? left.dosage_form_en, b: right.dosage_form_ar ?? right.dosage_form_en },
    { key: 'route', label: 'طريقة الاستخدام', a: left.route_en, b: right.route_en },
    { key: 'marketing_company', label: 'الشركة المسوّقة', a: left.marketing_company, b: right.marketing_company },
    { key: 'legal_status', label: 'الحالة النظامية', a: left.legal_status, b: right.legal_status },
    { key: 'listing_status', label: 'الحالة في السجل', a: listing(left), b: listing(right) },
    { key: 'price', label: 'السعر المسجّل', a: priceText(left), b: priceText(right) },
  ];

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content}>
        <Row gap={10} style={{ alignItems: 'stretch' }}>
          {[left, right].map((side) => (
            <Pressable
              key={side.register_number}
              style={{ flex: 1 }}
              onPress={() => router.push({ pathname: '/drug/[register]', params: { register: side.register_number } })}
            >
              <Card style={{ gap: 4, flex: 1 }}>
                <T weight={700}>{displayName(side)}</T>
                {side.trade_name_en ? (
                  <T size={12.5} color={c.ink2} latin align="right">
                    {side.trade_name_en}
                  </T>
                ) : null}
                <T size={12} color={c.ink2} latin align="right">
                  {side.register_number}
                </T>
              </Card>
            </Pressable>
          ))}
        </Row>

        <View style={{ gap: 6 }}>
          <Pill label={tier.label} tone={tier.tone} radiusSize={radius.md} icon={tier.icon} />
          <T size={12.5} color={c.ink2}>
            الحكم محسوب بقواعد ثابتة من بيانات السجل. الصيدلي أو الدكتور هو اللي يقرر.
          </T>
        </View>

        <View style={{ gap: 10 }}>
          <H2>المقارنة</H2>
          {rows.map((r) => {
            const differs = differences.includes(r.key);
            return (
              <Card key={r.key} style={{ gap: 6, borderWidth: differs ? 1.5 : 0, borderColor: c.wn }}>
                <Row style={{ justifyContent: 'space-between' }}>
                  <T size={13} color={c.ink2}>
                    {r.label}
                  </T>
                  {differs ? <Pill tone="wn" label="مختلف" /> : null}
                </Row>
                <Row gap={12} style={{ alignItems: 'flex-start' }}>
                  <T size={14} weight={600} style={{ flex: 1 }}>
                    {r.a ?? 'غير مذكور'}
                  </T>
                  <T size={14} weight={600} style={{ flex: 1 }}>
                    {r.b ?? 'غير مذكور'}
                  </T>
                </Row>
              </Card>
            );
          })}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { paddingTop: 16, paddingHorizontal: 16, paddingBottom: 60, gap: 22 },
});
