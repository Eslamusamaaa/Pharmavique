// B1 · Home · patient (pharmavique-wireframes/PvB1.dc.html)
import { Image } from 'expo-image';
import { router } from 'expo-router';
import {
  CaretDownIcon,
  ClockCounterClockwiseIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  ScanIcon,
  UserCircleIcon,
} from 'phosphor-react-native';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DisclaimerBar, Row, T } from '@/components/ui';
import { useRecentActions, useRecents, type Recent } from '@/state/recents';
import { cardShadow, radius, useTheme } from '@/theme';

function openRecent(r: Recent) {
  if (r.register) router.push({ pathname: '/drug/[register]', params: { register: r.register } });
  else router.push({ pathname: '/search', params: { q: r.query } });
}

export default function Home() {
  const { c, isDark } = useTheme();
  const recents = useRecents();
  const { clear } = useRecentActions();

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.header}>
        <Image
          source={isDark ? require('@/assets/images/logo-white.png') : require('@/assets/images/logo-h.png')}
          style={{ height: 30, width: 112 }}
          contentFit="contain"
          accessibilityLabel="Pharmavique"
        />
        <Pressable
          onPress={() => router.push('/account')}
          style={[styles.role, { backgroundColor: c.prs }]}
          accessibilityRole="button"
          accessibilityLabel="الدور: مريض"
        >
          <UserCircleIcon size={20} color={c.ink} />
          <T size={14}>مريض</T>
          <CaretDownIcon size={14} color={c.ink} />
        </Pressable>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <T size={28} weight={700} style={{ lineHeight: 39 }}>
          عن أي دواء تريد أن تعرف؟
        </T>
        <View style={{ gap: 14 }}>
          <Pressable
            onPress={() => router.push({ pathname: '/search', params: { focus: '1' } })}
            style={[styles.searchBox, { backgroundColor: c.sf }, cardShadow]}
            accessibilityRole="search"
          >
            <MagnifyingGlassIcon size={24} color={c.ink2} style={{ marginHorizontal: 14 }} />
            <T size={17} color={c.ink2} style={{ flex: 1 }}>
              ابحث بالاسم أو المادة الفعالة
            </T>
          </Pressable>
          <Row gap={12}>
            <Pressable
              onPress={() => router.push('/scan')}
              style={[styles.action, { backgroundColor: c.pr }]}
              accessibilityRole="button"
            >
              <ScanIcon size={28} color={c.prt} />
              <T weight={600} color={c.prt} align="center">
                مسح علبة الدواء
              </T>
            </Pressable>
            <Pressable
              onPress={() => router.push({ pathname: '/search', params: { voice: '1' } })}
              style={[styles.action, { backgroundColor: c.sf }, cardShadow]}
              accessibilityRole="button"
            >
              <MicrophoneIcon size={28} color={c.pr} />
              <T weight={600} color={c.pr} align="center">
                بحث صوتي
              </T>
            </Pressable>
          </Row>
        </View>
        {recents.length > 0 ? (
          <View style={{ gap: 6 }}>
            <Row style={{ justifyContent: 'space-between' }}>
              <T size={18} weight={700}>
                آخر عمليات البحث
              </T>
              <Pressable onPress={clear} style={styles.clear} accessibilityRole="button">
                <T size={13} color={c.ink2}>
                  مسح
                </T>
              </Pressable>
            </Row>
            {recents.slice(0, 5).map((r) => (
              <Pressable key={r.register ?? r.query} onPress={() => openRecent(r)} style={styles.recent}>
                <ClockCounterClockwiseIcon size={20} color={c.ink2} />
                <T style={{ flex: 1 }} numberOfLines={1}>
                  {r.ar}
                </T>
                {r.en ? (
                  <T size={13} color={c.ink2} latin numberOfLines={1} style={{ maxWidth: '45%' }}>
                    {r.en}
                  </T>
                ) : null}
              </Pressable>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: {
    height: 52,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
  },
  role: {
    minHeight: 44,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
  },
  content: { paddingTop: 32, paddingHorizontal: 16, paddingBottom: 16, gap: 28 },
  searchBox: { minHeight: 60, borderRadius: radius.lg, flexDirection: 'row-reverse', alignItems: 'center' },
  action: { flex: 1, minHeight: 76, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center', gap: 2 },
  clear: { minHeight: 44, justifyContent: 'center' },
  recent: { minHeight: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
});
