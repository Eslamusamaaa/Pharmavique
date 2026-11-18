import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import { ApiError, displayName, searchDrugs, type SearchHit } from '@/api/client';
import { Badge, Body, Card, Disclaimer, Loading, Message, SearchBox } from '@/components/ui';
import { colors } from '@/theme';

type State =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'done'; hits: SearchHit[] }
  | { kind: 'error'; detail: string };

export default function Search() {
  const params = useLocalSearchParams<{ q?: string }>();
  const [text, setText] = useState(params.q ?? '');
  const [state, setState] = useState<State>({ kind: 'idle' });

  useEffect(() => {
    const q = text.trim();
    if (!q) {
      setState({ kind: 'idle' });
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState({ kind: 'loading' });
      searchDrugs(q, controller.signal)
        .then((r) => setState({ kind: 'done', hits: r.results }))
        .catch((e: unknown) => {
          if ((e as Error).name === 'AbortError') return;
          const status = e instanceof ApiError ? e.status : null;
          setState({
            kind: 'error',
            detail:
              status === null
                ? 'مش قادر أوصل للسيرفر. اتأكد إن الـ API شغال وإن الموبايل على نفس الشبكة.'
                : `السيرفر رد بخطأ (${status}).`,
          });
        });
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  return (
    <View style={styles.screen}>
      <SearchBox value={text} onChangeText={setText} autoFocus />
      {state.kind === 'idle' && <Message title="اكتب اسم الدواء" />}
      {state.kind === 'loading' && <Loading />}
      {state.kind === 'error' && <Message title="حصلت مشكلة" detail={state.detail} />}
      {state.kind === 'done' && state.hits.length === 0 && (
        <Message title="مفيش نتايج" detail="جرّب الاسم العلمي أو اكتبه بطريقة تانية." />
      )}
      {state.kind === 'done' && state.hits.length > 0 && (
        <FlatList
          data={state.hits}
          keyExtractor={(h) => h.register_number}
          contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
          keyboardShouldPersistTaps="handled"
          ListFooterComponent={<Disclaimer />}
          renderItem={({ item }) => <HitCard hit={item} />}
        />
      )}
    </View>
  );
}

function HitCard({ hit }: { hit: SearchHit }) {
  const withdrawn = hit.listing_status !== 'listed';
  return (
    <Pressable
      onPress={() =>
        router.push({ pathname: '/drug/[register]', params: { register: hit.register_number } })
      }
      style={({ pressed }) => pressed && { opacity: 0.7 }}
    >
      <Card>
        <Text style={styles.name}>{displayName(hit)}</Text>
        {hit.trade_name_en && hit.trade_name_ar ? (
          <Text style={styles.latin}>{hit.trade_name_en}</Text>
        ) : null}
        <Body muted>{hit.ingredients.join(' + ')}</Body>
        <View style={styles.meta}>
          <Body muted>{hit.dosage_form_ar ?? hit.dosage_form_en ?? ''}</Body>
          {hit.exact ? <Badge label="تطابق تام" tone="ok" /> : null}
          {withdrawn ? <Badge label="غير مدرج حالياً" tone="danger" /> : null}
        </View>
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, padding: 16, gap: 12 },
  name: { fontSize: 16, fontWeight: '700', color: colors.ink, textAlign: 'right' },
  latin: { fontSize: 13, color: colors.ink2, textAlign: 'left' },
  meta: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
});
