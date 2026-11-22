// Search a drug by name and add it to my medicines with one tap.
import { MagnifyingGlassIcon, PlusIcon } from 'phosphor-react-native';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';

import { displayName, searchDrugs, type SearchHit } from '@/api/client';
import { DrugPicture } from '@/components/DrugPicture';
import { Card, T } from '@/components/ui';
import { fonts, useTheme } from '@/theme';

export function AddMedicine({ saved, onAdd }: { saved: Set<string>; onAdd: (register: string) => void }) {
  const { c } = useTheme();
  const [text, setText] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);

  useEffect(() => {
    const q = text.trim();
    if (q.length < 2) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchDrugs(q, controller.signal, 5)
        .then((r) => setHits(r.results))
        .catch(() => setHits([]));
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  return (
    <View style={{ gap: 8 }}>
      <View style={[styles.search, { backgroundColor: c.sf, borderColor: c.ln }]}>
        <MagnifyingGlassIcon size={20} color={c.ink2} />
        <TextInput
          value={text}
          onChangeText={setText}
          placeholder="ابحث عن دواء عشان تضيفه"
          placeholderTextColor={c.ink2}
          style={[styles.input, { color: c.ink, fontFamily: fonts.ar[400] }]}
          returnKeyType="search"
        />
      </View>
      {hits.map((h) => {
        const added = saved.has(h.register_number);
        return (
          <Pressable
            key={h.register_number}
            disabled={added}
            onPress={() => {
              onAdd(h.register_number);
              setText('');
              setHits([]);
            }}
          >
            <Card style={styles.hit}>
              <DrugPicture register={h.register_number} size={44} />
              <View style={{ flex: 1 }}>
                <T weight={600} numberOfLines={1}>
                  {displayName(h)}
                </T>
                <T size={12.5} color={c.ink2} latin align="right" numberOfLines={1}>
                  {h.ingredients.join(' + ')}
                </T>
              </View>
              {added ? (
                <T size={13} color={c.ink2}>
                  مضاف
                </T>
              ) : (
                <View style={[styles.plus, { backgroundColor: c.pr }]}>
                  <PlusIcon size={18} color={c.prt} weight="bold" />
                </View>
              )}
            </Card>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  search: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: 12, paddingHorizontal: 12 },
  input: { flex: 1, fontSize: 16, textAlign: 'right', paddingVertical: 12 },
  hit: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 10 },
  plus: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
});
