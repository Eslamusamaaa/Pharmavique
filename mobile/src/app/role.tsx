// First launch: who is using Pharmavique. No account is created; the choice stays on this device.
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { BuildingsIcon, FirstAidKitIcon, UserIcon } from '@/components/icons';
import type { ComponentType } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { T } from '@/components/ui';
import { ROLES, useRole, type Role } from '@/state/role';
import { cardShadow, radius, useTheme } from '@/theme';

const ICONS: Record<Role, ComponentType<{ size: number; color: string }>> = {
  patient: UserIcon,
  pharmacist: FirstAidKitIcon,
  company: BuildingsIcon,
};

export default function RolePicker() {
  const { c, isDark } = useTheme();
  const { role, setRole } = useRole();

  const choose = async (key: Role) => {
    await setRole(key);
    if (router.canGoBack()) router.back();
    else router.replace('/');
  };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={styles.content}>
        <Image
          source={isDark ? require('@/assets/images/logo-white.png') : require('@/assets/images/logo-h.png')}
          style={{ height: 34, width: 130, alignSelf: 'flex-end' }}
          contentFit="contain"
          accessibilityLabel="Pharmavique"
        />
        <T size={26} weight={700} style={{ lineHeight: 38 }}>
          من يستخدم التطبيق؟
        </T>
        <T size={15} color={c.ink2}>
          نعرض لك ما يناسبك. تقدر تغيّر اختيارك في أي وقت من صفحة حسابي.
        </T>
        <View style={{ gap: 12, marginTop: 8 }}>
          {ROLES.map((r) => {
            const Icon = ICONS[r.key];
            const selected = role === r.key;
            return (
              <Pressable
                key={r.key}
                onPress={() => choose(r.key)}
                accessibilityRole="button"
                style={[
                  styles.card,
                  { backgroundColor: c.sf, borderColor: selected ? c.pr : c.ln, borderWidth: selected ? 2 : 1 },
                  cardShadow,
                ]}
              >
                <View style={[styles.icon, { backgroundColor: c.prs }]}>
                  <Icon size={28} color={c.pr} />
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <T size={18} weight={700}>
                    {r.label}
                  </T>
                  <T size={14} color={c.ink2}>
                    {r.hint}
                  </T>
                </View>
              </Pressable>
            );
          })}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 20, gap: 14 },
  card: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, padding: 16, borderRadius: radius.lg, minHeight: 84 },
  icon: { width: 52, height: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
