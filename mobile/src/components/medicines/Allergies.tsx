// My allergies: chips to remove, and a box to add one by active ingredient. The match is by
// ingredient name only, so it is a prompt to ask the pharmacist, never a clearance.
import { XIcon } from '@/components/icons';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { searchIngredients } from '@/api/me';
import { Card, H2, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

export function Allergies({
  items,
  note,
  onAdd,
  onRemove,
}: {
  items: string[];
  note: string;
  onAdd: (ingredient: string) => void;
  onRemove: (ingredient: string) => void;
}) {
  const { c } = useTheme();
  const [typed, setTyped] = useState('');
  const [options, setOptions] = useState<string[]>([]);

  useEffect(() => {
    if (typed.trim().length < 2) {
      setOptions([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchIngredients(typed.trim(), controller.signal)
        .then(setOptions)
        .catch(() => setOptions([]));
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [typed]);

  return (
    <View style={{ gap: 10 }}>
      <H2>الحساسية</H2>
      <Card style={{ gap: 12 }}>
        {items.length > 0 ? (
          <Row gap={8} style={{ flexWrap: 'wrap' }}>
            {items.map((a) => (
              <Pressable
                key={a}
                onPress={() => onRemove(a)}
                accessibilityLabel={`احذف ${a}`}
                style={[styles.chip, { backgroundColor: c.wns }]}
              >
                <XIcon size={14} color={c.wn} />
                <T size={13} weight={600} color={c.wn} latin>
                  {a}
                </T>
              </Pressable>
            ))}
          </Row>
        ) : (
          <T size={14} color={c.ink2}>
            ما سجّلت أي حساسية. أضف المادة الفعالة اللي عندك منها حساسية.
          </T>
        )}
        <TextInput
          value={typed}
          onChangeText={setTyped}
          placeholder="اكتب أول حروف المادة الفعالة (بالإنجليزي)"
          placeholderTextColor={c.ink2}
          autoCapitalize="characters"
          autoCorrect={false}
          style={[styles.input, { borderColor: c.ln, color: c.ink, backgroundColor: c.bg }]}
        />
        {options.map((name) => (
          <Pressable
            key={name}
            onPress={() => {
              setTyped('');
              setOptions([]);
              onAdd(name);
            }}
            style={[styles.option, { borderColor: c.ln }]}
          >
            <T latin align="left">
              {name}
            </T>
          </Pressable>
        ))}
        <T size={12.5} color={c.ink2}>
          {note}
        </T>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, borderRadius: radius.pill, paddingHorizontal: 12, minHeight: 36 },
  input: { minHeight: 48, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 15, textAlign: 'left' },
  option: { minHeight: 44, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, justifyContent: 'center' },
});
