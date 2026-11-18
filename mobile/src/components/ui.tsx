import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import type { TextInputProps, ViewStyle } from 'react-native';

import { colors, DISCLAIMER, radius, shadow } from '@/theme';

export function Screen({ children }: { children: ReactNode }) {
  return <View style={styles.screen}>{children}</View>;
}

export function Card({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Title({ children }: { children: ReactNode }) {
  return <Text style={styles.title}>{children}</Text>;
}

export function Body({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return <Text style={[styles.body, muted && { color: colors.ink2 }]}>{children}</Text>;
}

export function SearchBox(props: TextInputProps) {
  return (
    <TextInput
      placeholder="اكتب اسم الدواء بالعربي أو الإنجليزي"
      placeholderTextColor={colors.ink2}
      autoCorrect={false}
      autoCapitalize="none"
      returnKeyType="search"
      style={styles.input}
      {...props}
    />
  );
}

export function Chip({ label, onPress }: { label: string; onPress?: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.chip, pressed && { opacity: 0.6 }]}>
      <Text style={styles.chipText}>{label}</Text>
    </Pressable>
  );
}

export function Badge({ label, tone }: { label: string; tone: 'ok' | 'warn' | 'danger' }) {
  const bg = { ok: colors.okSoft, warn: colors.warnSoft, danger: colors.dangerSoft }[tone];
  const fg = { ok: colors.ok, warn: colors.warn, danger: colors.danger }[tone];
  return (
    <View style={[styles.badge, { backgroundColor: bg }]}>
      <Text style={[styles.badgeText, { color: fg }]}>{label}</Text>
    </View>
  );
}

export function Loading() {
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.primary} />
    </View>
  );
}

export function Message({ title, detail }: { title: string; detail?: string }) {
  return (
    <View style={styles.center}>
      <Text style={styles.title}>{title}</Text>
      {detail ? <Body muted>{detail}</Body> : null}
    </View>
  );
}

export function Disclaimer() {
  return <Text style={styles.disclaimer}>{DISCLAIMER}</Text>;
}

export function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.bg, padding: 16, gap: 12 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 14,
    gap: 6,
    ...shadow,
  },
  title: { fontSize: 18, fontWeight: '700', color: colors.ink, textAlign: 'right' },
  body: { fontSize: 14, color: colors.ink, textAlign: 'right', lineHeight: 21 },
  input: {
    backgroundColor: colors.surface,
    borderRadius: radius.control,
    borderWidth: 1,
    borderColor: colors.line,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.ink,
    textAlign: 'right',
    writingDirection: 'rtl',
  },
  chip: {
    backgroundColor: colors.primarySoft,
    borderRadius: radius.chip,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  chipText: { color: colors.primary, fontWeight: '600' },
  badge: { alignSelf: 'flex-end', borderRadius: radius.chip, paddingHorizontal: 10, paddingVertical: 3 },
  badgeText: { fontSize: 12, fontWeight: '700' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24 },
  disclaimer: {
    fontSize: 12,
    color: colors.warn,
    backgroundColor: colors.warnSoft,
    borderRadius: radius.control,
    padding: 10,
    textAlign: 'right',
  },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', gap: 12, paddingVertical: 6 },
  rowLabel: { color: colors.ink2, fontSize: 13, textAlign: 'right' },
  rowValue: { color: colors.ink, fontSize: 14, flexShrink: 1, textAlign: 'left' },
});
