// Small building blocks of the account screen: a grouped card of rows, one tappable row, a switch row.
import { CaretLeftIcon } from '@/components/icons';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Switch, View } from 'react-native';

import { Card, T } from '@/components/ui';
import { useTheme } from '@/theme';

export function Group({ title, children }: { title?: string; children: ReactNode }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 8, alignSelf: 'stretch' }}>
      {title ? (
        <T size={13} weight={600} color={c.ink2} style={{ paddingHorizontal: 4 }}>
          {title}
        </T>
      ) : null}
      <Card style={{ padding: 0, overflow: 'hidden' }}>{children}</Card>
    </View>
  );
}

export function LinkRow({
  label,
  hint,
  onPress,
  danger,
  last,
}: {
  label: string;
  hint?: string;
  onPress: () => void;
  danger?: boolean;
  last?: boolean;
}) {
  const { c } = useTheme();
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      style={[styles.row, !last && { borderBottomWidth: 1, borderBottomColor: c.ln }]}
    >
      <View style={{ flex: 1 }}>
        <T weight={600} color={danger ? c.rd : c.ink}>
          {label}
        </T>
        {hint ? (
          <T size={12.5} color={c.ink2}>
            {hint}
          </T>
        ) : null}
      </View>
      {danger ? null : <CaretLeftIcon size={18} color={c.ink2} />}
    </Pressable>
  );
}

export function SwitchRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: boolean;
  onChange: (on: boolean) => void;
}) {
  const { c } = useTheme();
  return (
    <View style={styles.row}>
      <View style={{ flex: 1 }}>
        <T weight={600}>{label}</T>
        <T size={12.5} color={c.ink2}>
          {hint}
        </T>
      </View>
      <Switch value={value} onValueChange={onChange} accessibilityLabel={label} />
    </View>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: 56, flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingVertical: 10 },
});
