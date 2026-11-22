// B1 · Home · patient (pharmavique-wireframes/PvB1.dc.html)
import { Image } from 'expo-image';
import { router } from 'expo-router';
import {
  CaretDownIcon,
  ChatCircleDotsIcon,
  ClockCounterClockwiseIcon,
  MagnifyingGlassIcon,
  MapPinIcon,
  MicrophoneIcon,
  ScanIcon,
  UserCircleIcon,
  WarningIcon,
} from 'phosphor-react-native';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DisclaimerBar, Row, T } from '@/components/ui';
import { useWide } from '@/lib/layout';
import { useRecentActions, useRecents, type Recent } from '@/state/recents';
import { roleInfo, useRole } from '@/state/role';
import { cardShadow, radius, useTheme } from '@/theme';

function openRecent(r: Recent) {
  if (r.register) router.push({ pathname: '/drug/[register]', params: { register: r.register } });
  else router.push({ pathname: '/search', params: { q: r.query } });
}

export default function Home() {
  const { c, isDark } = useTheme();
  const recents = useRecents();
  const { clear } = useRecentActions();
  const { role } = useRole();
  const current = roleInfo(role ?? 'patient');
  const wide = useWide();
  // three cards in a row on a computer, one under the other on a phone
  const tile = wide ? { flexBasis: '31%', flexGrow: 1 } : { flexBasis: '100%' };
  const page = wide ? ({ maxWidth: 1100, width: '100%', alignSelf: 'center' } as const) : null;

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
          onPress={() => router.push('/role')}
          style={[styles.role, { backgroundColor: c.prs }]}
          accessibilityRole="button"
          accessibilityLabel={`الدور: ${current.label}`}
        >
          <UserCircleIcon size={20} color={c.ink} />
          <T size={14} numberOfLines={1} style={{ maxWidth: 150 }}>
            {current.label}
          </T>
          <CaretDownIcon size={14} color={c.ink} />
        </Pressable>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={[styles.content, page]} keyboardShouldPersistTaps="handled">
        <T size={28} weight={700} style={{ lineHeight: 39 }}>
          {current.greeting}
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
              onPress={() => router.push('/voice')}
              style={[styles.action, { backgroundColor: c.sf }, cardShadow]}
              accessibilityRole="button"
            >
              <MicrophoneIcon size={28} color={c.pr} />
              <T weight={600} color={c.pr} align="center">
                بحث صوتي
              </T>
            </Pressable>
          </Row>
          <View style={{ flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 14 }}>
          <Pressable
            onPress={() => router.push('/assistant')}
            style={[styles.assistant, tile, { backgroundColor: c.sf, borderColor: c.ln }]}
            accessibilityRole="button"
          >
            <ChatCircleDotsIcon size={26} color={c.pr} />
            <View style={{ flex: 1 }}>
              <T weight={700}>اسأل المساعد عن أي دواء</T>
              <T size={13} color={c.ink2}>
                إجابات من بيانات الهيئة الرسمية، ومعها صوت باللهجة السعودية
              </T>
            </View>
          </Pressable>
          <Pressable
            onPress={() => router.push('/pharmacies')}
            style={[styles.assistant, tile, { backgroundColor: c.sf, borderColor: c.ln }]}
            accessibilityRole="button"
          >
            <MapPinIcon size={26} color={c.pr} />
            <View style={{ flex: 1 }}>
              <T weight={700}>صيدليات مرخّصة قريبة</T>
              <T size={13} color={c.ink2}>
                من قائمة الهيئة، حسب المدينة. ما فيها معلومة عن توفر الدواء
              </T>
            </View>
          </Pressable>
          {role === 'pharmacist' || role === 'patient' ? (
            <Pressable
              onPress={() => router.push(role === 'pharmacist' ? '/interactions' : '/medicines')}
              style={[styles.assistant, tile, { backgroundColor: c.sf, borderColor: c.ln }]}
              accessibilityRole="button"
            >
              <WarningIcon size={26} color={c.pr} />
              <View style={{ flex: 1 }}>
                <T weight={700}>{role === 'pharmacist' ? 'فحص التداخل بين الأدوية' : 'أدويتي والتداخل بينها'}</T>
                <T size={13} color={c.ink2}>
                  {role === 'pharmacist'
                    ? 'أضف دوائين أو أكثر لترى التداخلات المسجّلة'
                    : 'أضف أدويتك لتعرف إن كان بينها تداخل مسجّل'}
                </T>
              </View>
            </Pressable>
          ) : null}
          </View>
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
  assistant: {
    minHeight: 64,
    borderRadius: radius.lg,
    borderWidth: 1,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  recent: { minHeight: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
});
