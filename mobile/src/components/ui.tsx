// Building blocks that follow pharmavique-wireframes (D2 · Components). Arabic-first, right to left:
// rows use `row-reverse` so the first child sits on the right, like the wireframes.
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import type { StyleProp, TextStyle, ViewStyle } from 'react-native';
import { router } from 'expo-router';
import { CheckCircleIcon, InfoIcon, WarningIcon } from '@/components/icons';

import { cardShadow, DISCLAIMER, fonts, radius, useTheme, type Weight } from '@/theme';

type TProps = {
  children: ReactNode;
  size?: number;
  weight?: Weight;
  color?: string;
  latin?: boolean; // Latin drug names and digits use Inter and run left to right
  align?: 'right' | 'left' | 'center';
  style?: StyleProp<TextStyle>;
  numberOfLines?: number;
};

/** Text with the wireframe type scale: Plex Sans Arabic for Arabic, Inter for Latin. */
export function T({ children, size = 16, weight = 400, color, latin, align, style, numberOfLines }: TProps) {
  const { c } = useTheme();
  return (
    <Text
      numberOfLines={numberOfLines}
      style={[
        {
          fontFamily: (latin ? fonts.latin : fonts.ar)[weight],
          fontSize: size,
          lineHeight: Math.round(size * (latin ? 1.45 : 1.7)),
          color: color ?? c.ink,
          textAlign: align ?? 'right',
          writingDirection: latin ? 'ltr' : 'rtl',
        },
        style,
      ]}
    >
      {children}
    </Text>
  );
}

/** Row laid out right to left. */
export function Row({ children, gap = 8, style }: { children: ReactNode; gap?: number; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ flexDirection: 'row-reverse', alignItems: 'center', gap }, style]}>{children}</View>;
}

/** The persistent disclaimer bar (wireframe note 1: on every home, search and drug screen). */
export function DisclaimerBar() {
  const { c } = useTheme();
  return (
    <View style={[styles.disclaimer, { backgroundColor: c.prs }]}>
      <InfoIcon size={16} color={c.pr} weight="fill" style={{ marginTop: 3 }} />
      <T size={12.5} style={{ flex: 1, lineHeight: 20 }}>
        {DISCLAIMER}
      </T>
      <Pressable onPress={() => router.push('/sources')} accessibilityRole="link" hitSlop={8}>
        <T size={12.5} weight={700} color={c.pr}>
          المصادر
        </T>
      </Pressable>
    </View>
  );
}

const GRADE_TONE = { official_sa: 'ok', official_foreign: 'neutral', unverified: 'wn' } as const;
const GRADE_LABEL = {
  official_sa: 'رسمي سعودي',
  official_foreign: 'مرجع رسمي أجنبي',
  unverified: 'غير موثّق',
} as const;

/** The trust grade of a piece of data: always an icon and a word, never colour alone. */
export function TrustBadge({ grade, label }: { grade: keyof typeof GRADE_TONE; label?: string }) {
  const { c } = useTheme();
  const tone = GRADE_TONE[grade] ?? 'wn';
  const color = tone === 'ok' ? c.ok : tone === 'neutral' ? c.pr : c.wn;
  return (
    <Pill
      tone={tone}
      label={label ?? GRADE_LABEL[grade] ?? GRADE_LABEL.unverified}
      icon={
        tone === 'wn' ? (
          <WarningIcon size={14} color={color} weight="fill" />
        ) : (
          <CheckCircleIcon size={14} color={color} weight="fill" />
        )
      }
    />
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const { c } = useTheme();
  return <View style={[styles.card, { backgroundColor: c.sf }, cardShadow, style]}>{children}</View>;
}

export function H2({ children }: { children: ReactNode }) {
  return (
    <T size={18} weight={700}>
      {children}
    </T>
  );
}

/** Small rounded label; `tone` picks the semantic pair (always icon + label, never color alone). */
export function Pill({
  label,
  icon,
  tone = 'neutral',
  radiusSize = radius.pill,
}: {
  label: string;
  icon?: ReactNode;
  tone?: 'neutral' | 'ok' | 'wn' | 'rd' | 'or' | 'muted';
  radiusSize?: number;
}) {
  const { c } = useTheme();
  const pair = {
    neutral: [c.prs, c.pr],
    ok: [c.oks, c.ok],
    wn: [c.wns, c.wn],
    rd: [c.rds, c.rd],
    or: [c.ors, c.or],
    muted: [c.bg, c.ink2],
  }[tone];
  return (
    <View style={[styles.pill, { backgroundColor: pair[0], borderRadius: radiusSize }]}>
      {icon}
      <T size={12.5} weight={600} color={pair[1]}>
        {label}
      </T>
    </View>
  );
}

export function Loading() {
  const { c } = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator color={c.pr} />
    </View>
  );
}

export function Message({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={styles.center}>
      <T size={18} weight={700} align="center">
        {title}
      </T>
      {detail ? (
        <T size={14} color={c.ink2} align="center">
          {detail}
        </T>
      ) : null}
      {action}
    </View>
  );
}

export function PrimaryButton({ label, icon, onPress, outline, style }: {
  label: string;
  icon?: ReactNode;
  onPress?: () => void;
  outline?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        outline
          ? { borderWidth: 1.5, borderColor: c.pr, backgroundColor: 'transparent' }
          : { backgroundColor: c.pr },
        pressed && { opacity: 0.75 },
        style,
      ]}
    >
      {icon}
      <T weight={outline ? 600 : 700} color={outline ? c.pr : c.prt}>
        {label}
      </T>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  disclaimer: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 8, paddingVertical: 8, paddingHorizontal: 16 },
  card: { borderRadius: radius.lg, paddingVertical: 14, paddingHorizontal: 16, gap: 6 },
  pill: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5, paddingVertical: 3, paddingHorizontal: 10, alignSelf: 'flex-end' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8, padding: 24 },
  button: { minHeight: 48, borderRadius: radius.md, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 12 },
});
