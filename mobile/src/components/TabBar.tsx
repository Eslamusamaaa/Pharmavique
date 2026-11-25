// Navigation from the wireframes (B1, B3): a bottom tab bar on a phone, a right-hand rail on a
// computer (the same tabs, right to left).
import type { BottomTabBarProps } from 'expo-router/js-tabs';
import { HouseIcon, MagnifyingGlassIcon, PillIcon, ScanIcon, UserIcon } from '@/components/icons';
import { Image } from 'expo-image';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useWide } from '@/lib/layout';
import { T } from '@/components/ui';
import { useTheme } from '@/theme';

const TABS = {
  index: { label: 'الرئيسية', Icon: HouseIcon },
  search: { label: 'بحث', Icon: MagnifyingGlassIcon },
  scan: { label: 'المسح الضوئي', Icon: ScanIcon },
  medicines: { label: 'أدويتي', Icon: PillIcon },
  account: { label: 'حسابي', Icon: UserIcon },
} as const;

export function TabBar({ state, emitter, navigateToTab }: BottomTabBarProps) {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const wide = useWide();
  return (
    <View
      style={
        wide
          ? [styles.rail, { backgroundColor: c.sf, borderLeftColor: c.ln }]
          : [styles.bar, { backgroundColor: c.sf, borderTopColor: c.ln, paddingBottom: Math.max(insets.bottom, 22) }]
      }
    >
      {wide ? <Image source={require('@/assets/images/mark.png')} style={styles.mark} contentFit="contain" /> : null}
      {state.routes.map((route, index) => {
        const tab = TABS[route.name as keyof typeof TABS];
        if (!tab) return null;
        const active = state.index === index;
        const color = active ? c.pr : c.ink2;
        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            onPress={() => {
              const event = emitter.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!active && !event.defaultPrevented) navigateToTab(route.key);
            }}
            style={wide ? [styles.railTab, active && { backgroundColor: c.prs }] : styles.tab}
          >
            <tab.Icon size={24} color={color} weight={active ? 'fill' : 'regular'} />
            <T size={11.5} weight={active ? 700 : 400} color={color} align="center">
              {tab.label}
            </T>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  rail: { width: 112, height: '100%', alignItems: 'stretch', gap: 6, paddingTop: 20, paddingHorizontal: 10, borderLeftWidth: 1 },
  mark: { width: 48, height: 48, alignSelf: 'center', marginBottom: 18 },
  railTab: { alignItems: 'center', gap: 4, paddingVertical: 12, borderRadius: 14, minHeight: 64 },
  // row-reverse: the first tab (home) sits on the right, as in the wireframes
  bar: { flexDirection: 'row-reverse', paddingTop: 8, paddingHorizontal: 8, borderTopWidth: 1 },
  tab: { flex: 1, alignItems: 'center', gap: 2, minHeight: 44 },
});
