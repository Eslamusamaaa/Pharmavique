// One saved medicine: picture, name, allergy warnings, taken-now switch and remove.
import { router } from 'expo-router';
import { TrashIcon, WarningIcon } from '@/components/icons';
import { Pressable, StyleSheet, View } from 'react-native';

import { displayName } from '@/api/client';
import type { SavedMedicine } from '@/api/me';
import { DrugPicture } from '@/components/DrugPicture';
import { Card, Pill, Row, T } from '@/components/ui';
import { useTheme } from '@/theme';

export function SavedCard({
  item,
  onToggle,
  onRemove,
}: {
  item: SavedMedicine;
  onToggle: () => void;
  onRemove: () => void;
}) {
  const { c } = useTheme();
  const past = item.status === 'past';
  return (
    <Card style={{ gap: 10, opacity: past ? 0.75 : 1 }}>
      <Row gap={12} style={{ alignItems: 'flex-start' }}>
        <Pressable
          onPress={() => router.push({ pathname: '/drug/[register]', params: { register: item.register_number } })}
          style={styles.main}
        >
          <DrugPicture register={item.register_number} size={56} />
          <View style={{ flex: 1 }}>
            <T weight={700} numberOfLines={2}>
              {item.product ? displayName(item.product) : item.register_number}
            </T>
            {item.product?.trade_name_en ? (
              <T size={13} color={c.ink2} latin align="right" numberOfLines={1}>
                {item.product.trade_name_en}
              </T>
            ) : null}
          </View>
        </Pressable>
        <Pressable onPress={onRemove} accessibilityLabel="احذف من أدويتي" style={styles.iconBtn}>
          <TrashIcon size={20} color={c.ink2} />
        </Pressable>
      </Row>
      {item.allergy_matches.map((x) => (
        <Pill
          key={`${x.allergy}-${x.ingredient}`}
          tone="wn"
          label={`فيه ${x.ingredient}، وأنت مسجّل حساسية من ${x.allergy}. اسأل الصيدلي`}
          icon={<WarningIcon size={14} color={c.wn} weight="fill" />}
        />
      ))}
      <Pressable onPress={onToggle} accessibilityRole="button" style={styles.toggle}>
        <T size={13.5} weight={600} color={c.pr}>
          {past ? 'آخذه الحين' : 'ما آخذه الحين (كنت آخذه قبل)'}
        </T>
      </Pressable>
    </Card>
  );
}

const styles = StyleSheet.create({
  main: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  toggle: { minHeight: 40, justifyContent: 'center' },
});
