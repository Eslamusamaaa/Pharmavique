// Operator data-quality board: what is missing in the catalog and how the daily refresh is doing.
// Read-only. A number that cannot be known is shown as unknown, never as zero.
import { router } from 'expo-router';
import { ArrowRightIcon, CheckCircleIcon, WarningIcon } from '@/components/icons';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicCompanyError, getQuality, type Quality } from '@/api/company';
import { PendingAccounts } from '@/components/PendingAccounts';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { radius, useTheme } from '@/theme';

const num = (n: number | null | undefined) => (n === null || n === undefined ? 'غير معروف' : n.toLocaleString('ar-EG'));

export default function Operator() {
  const { c } = useTheme();
  const { account } = useAccount();
  const [data, setData] = useState<Quality | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await getQuality());
      setError(null);
    } catch (e) {
      setError(arabicCompanyError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (account) load();
    else if (account === null) setLoading(false);
  }, [account, load]);

  const header = (
    <View style={styles.topBar}>
      <Pressable
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/account'))}
        style={styles.iconBtn}
        accessibilityLabel="رجوع"
      >
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        جودة البيانات
      </T>
    </View>
  );

  if (account === null) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Message title="هذي الشاشة لمشغّل المنصة" detail="سجّل الدخول بحساب المشغّل." />
      </SafeAreaView>
    );
  }
  if (loading) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Loading />
      </SafeAreaView>
    );
  }
  if (error || !data) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Message
          title={error ?? 'حصلت مشكلة'}
          action={
            <Pressable onPress={load} style={[styles.main, { backgroundColor: c.pr }]}>
              <T weight={700} color={c.prt}>
                حاول مرة ثانية
              </T>
            </Pressable>
          }
        />
      </SafeAreaView>
    );
  }

  const k = data.catalog;
  const rows: [string, number][] = [
    ['بدون سعر', k.listed_without_price],
    ['بدون مواد فعالة', k.listed_without_ingredients],
    ['فيه مادة بدون تركيز', k.listed_with_missing_strength],
    ['بدون شركة مصنّعة أو مسوّقة', k.listed_without_manufacturer],
    ['بدون صورة', k.listed_without_picture],
  ];
  const refresh = data.refresh;

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content}>
        <PendingAccounts />

        <Card style={{ gap: 4 }}>
          <T weight={700}>
            {num(k.listed)} دواء مسجّل · {num(k.withdrawn)} مسحوب · الإجمالي {num(k.products)}
          </T>
          <T size={13} color={c.ink2}>
            هذي الأعداد للأدوية المسجّلة (غير المسحوبة) إلا إذا كُتب غير ذلك.
          </T>
        </Card>

        <View style={{ gap: 8 }}>
          <H2>النواقص</H2>
          {rows.map(([label, value]) => (
            <Row key={label} style={{ justifyContent: 'space-between' }}>
              <T size={14} style={{ flex: 1 }}>
                {label}
              </T>
              <T weight={700}>{num(value)}</T>
            </Row>
          ))}
          <Row style={{ justifyContent: 'space-between' }}>
            <T size={14} style={{ flex: 1 }}>
              صورة حقيقية · صورة مولّدة
            </T>
            <T weight={700}>
              {num(k.listed_with_real_picture)} · {num(k.listed_with_generated_picture)}
            </T>
          </Row>
        </View>

        <View style={{ gap: 8 }}>
          <H2>التحديث اليومي</H2>
          {!refresh.available ? (
            <Pill tone="wn" label="ما فيه سجل تحديث على هذا السيرفر: الحالة غير معروفة" />
          ) : (
            <>
              <Pill
                tone={refresh.overdue ? 'rd' : 'ok'}
                label={
                  refresh.overdue
                    ? `متأخر: آخر تحديث من ${refresh.days_since_last} يوم`
                    : `آخر تحديث ${refresh.last_day}`
                }
                icon={
                  refresh.overdue ? (
                    <WarningIcon size={14} color={c.rd} weight="fill" />
                  ) : (
                    <CheckCircleIcon size={14} color={c.ok} weight="fill" />
                  )
                }
              />
              {refresh.days.map((d) => (
                <Card key={d.day} style={{ gap: 4 }}>
                  <T weight={700}>{d.day}</T>
                  {d.failed_steps.length > 0 ? (
                    <T size={14} color={c.rd}>
                      خطوات فشلت: {d.failed_steps.join('، ')}
                    </T>
                  ) : (
                    <T size={14} color={c.ok}>
                      كل الخطوات تمام
                    </T>
                  )}
                  <T size={13} color={c.ink2}>
                    تم تحميل {num(d.load?.loaded)} · تم تخطّي {num(d.load?.skipped)} · تم رفض {num(d.load?.rejected)}
                  </T>
                </Card>
              ))}
            </>
          )}
        </View>

        <View style={{ gap: 8 }}>
          <H2>القوائم الرسمية</H2>
          {k.lists.map((l) => (
            <Card key={l.list_name} style={{ gap: 2 }}>
              <T weight={700} latin align="left">
                {l.list_name}
              </T>
              <T size={13} color={c.ink2}>
                {num(l.rows)} صف · مربوط بدقة {num(l.linked_matched)} · محتمل {num(l.linked_possible)} · بدون ربط{' '}
                {num(l.unlinked)}
              </T>
            </Card>
          ))}
          <T size={12.5} color={c.ink2}>
            صف بدون ربط، وهذا طبيعي في القوائم اللي ليست عن الأدوية.
          </T>
        </View>

        <View style={{ gap: 8 }}>
          <H2>بيانات شاشات الشركات</H2>
          {data.analytics && data.analytics.built_at ? (
            <T size={14}>
              {num(data.analytics.products)} دواء · انبنت {new Date(data.analytics.built_at).toLocaleString('ar-EG')} ·{' '}
              {num(data.analytics.events_7d)} تغيير في آخر ٧ أيام
            </T>
          ) : (
            <Pill tone="wn" label="للحين ما انبنت: شغّل analytics-rebuild" />
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 22, paddingBottom: 80 },
  main: { minHeight: 48, paddingHorizontal: 24, borderRadius: radius.md, justifyContent: 'center' },
});
