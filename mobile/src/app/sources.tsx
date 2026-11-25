// Last update and sources: every source the app uses, its trust grade and when it was last updated.
// Public. A figure that is not known is shown as "غير معروف", never as zero or as today.
import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { friendlyError, getSources, type Sources } from '@/api/client';
import { ArrowRightIcon } from '@/components/icons';
import { Card, DisclaimerBar, H2, Loading, Message, Row, T, TrustBadge } from '@/components/ui';
import { useTheme } from '@/theme';

const date = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ar-SA-u-ca-gregory', { year: 'numeric', month: 'long', day: 'numeric' }) : 'غير معروف';
const count = (n: number | null) => (n === null ? 'غير معروف' : n.toLocaleString('ar-SA-u-nu-arab'));

export default function SourcesScreen() {
  const { c } = useTheme();
  const [data, setData] = useState<Sources | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await getSources());
    } catch (e) {
      setError(friendlyError(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.topBar}>
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))}
          style={styles.iconBtn}
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          آخر تحديث والمصادر
        </T>
      </View>
      {error ? (
        <Message title={error} />
      ) : !data ? (
        <Loading />
      ) : (
        <ScrollView contentContainerStyle={styles.content}>
          <DisclaimerBar />
          <View style={{ gap: 8 }}>
            <H2>درجات الثقة</H2>
            {data.grades.map((g) => (
              <Card key={g.grade} style={{ gap: 6 }}>
                <Row style={{ justifyContent: 'flex-start' }}>
                  <TrustBadge grade={g.grade} label={g.label_ar} />
                </Row>
                <T size={13.5} color={c.ink2}>
                  {g.meaning_ar}
                </T>
              </Card>
            ))}
          </View>

          <View style={{ gap: 8 }}>
            <H2>المصادر</H2>
            {data.sources.map((s) => (
              <Card key={s.id} style={{ gap: 6 }}>
                <Row style={{ justifyContent: 'space-between' }}>
                  <T weight={700} style={{ flex: 1 }}>
                    {s.name_ar}
                  </T>
                  <TrustBadge grade={s.grade} label={s.grade_label_ar} />
                </Row>
                <T size={13} color={c.ink2}>
                  {s.used_for_ar}
                </T>
                <T size={13} color={c.ink2}>
                  آخر تحديث: {date(s.last_updated)} · السجلات: {count(s.records)}
                </T>
                <T size={13} color={c.ink2}>
                  التحديث: {s.cadence_ar}
                </T>
                {s.url ? (
                  <Pressable onPress={() => Linking.openURL(s.url as string)} accessibilityRole="link">
                    <T size={13} weight={700} color={c.pr}>
                      افتح المصدر
                    </T>
                  </Pressable>
                ) : null}
              </Card>
            ))}
            <T size={12.5} color={c.ink2}>
              «غير معروف» معناها إن السيرفر ما يعرف الرقم أو التاريخ، مو إنه صفر.
            </T>
          </View>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 18, paddingBottom: 60 },
});
