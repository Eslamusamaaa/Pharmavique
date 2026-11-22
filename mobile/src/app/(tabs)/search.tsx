// B3 · Search results and B4 · Search while typing (pharmavique-wireframes/PvB1.dc.html, PvB3.dc.html)
import { router, useLocalSearchParams } from 'expo-router';
import {
  ArrowRightIcon,
  CameraIcon,
  CaretDownIcon,
  ClockCounterClockwiseIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  SortDescendingIcon,
  XCircleIcon,
  XIcon,
} from 'phosphor-react-native';
import { useEffect, useMemo, useRef, useState, type ComponentRef } from 'react';
import { FlatList, Modal, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { displayName, fold, friendlyError, searchDrugs, type SearchHit } from '@/api/client';
import { DrugPicture } from '@/components/DrugPicture';
import { Card, DisclaimerBar, Loading, Message, Pill, Row, T } from '@/components/ui';
import { useRecentActions, useRecents } from '@/state/recents';
import { cardShadow, fonts, radius, useTheme } from '@/theme';

type Results = { kind: 'idle' } | { kind: 'loading' } | { kind: 'done'; hits: SearchHit[] } | { kind: 'error'; detail: string };
type FilterKey = 'form' | 'company' | 'legal';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'form', label: 'الشكل الدوائي' },
  { key: 'company', label: 'الشركة' },
  { key: 'legal', label: 'الحالة النظامية' },
];

const LEGAL_AR: Record<string, string> = { OTC: 'بدون وصفة طبية', Prescription: 'بوصفة طبية' };

function valueOf(hit: SearchHit, key: FilterKey): string | null {
  if (key === 'form') return hit.dosage_form_ar ?? hit.dosage_form_en;
  if (key === 'company') return hit.marketing_company;
  return hit.legal_status ? LEGAL_AR[hit.legal_status] ?? hit.legal_status : null;
}

/** "Did you mean": shown only when no result name contains what was typed (a misspelling). */
function didYouMean(hits: SearchHit[], query: string): string | null {
  const q = fold(query);
  if (!hits.length || q.length < 3) return null;
  const contains = hits.some((h) =>
    [h.trade_name_ar, h.trade_name_en, ...h.ingredients].some((n) => n && fold(n).includes(q)),
  );
  if (contains) return null;
  const top = hits[0];
  const name = top.trade_name_ar ?? top.trade_name_en;
  return name ? name.split(/\s+/)[0] : null;
}

export default function Search() {
  const { c } = useTheme();
  const params = useLocalSearchParams<{ q?: string; focus?: string; voice?: string; compareWith?: string }>();
  const [text, setText] = useState(params.q ?? '');
  const [submitted, setSubmitted] = useState(params.q ?? '');
  const [focused, setFocused] = useState(!params.q);
  const [suggestions, setSuggestions] = useState<SearchHit[]>([]);
  const [results, setResults] = useState<Results>({ kind: 'idle' });
  const [filters, setFilters] = useState<Partial<Record<FilterKey, string>>>({});
  const [openFilter, setOpenFilter] = useState<FilterKey | null>(null);
  const input = useRef<ComponentRef<typeof TextInput>>(null);
  const recents = useRecents();
  const { add, remove } = useRecentActions();

  useEffect(() => {
    if (params.q) {
      setText(params.q);
      setSubmitted(params.q);
      setFocused(false);
    }
  }, [params.q]);

  // B4: suggestions while typing
  useEffect(() => {
    const q = text.trim();
    if (!focused || !q) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchDrugs(q, controller.signal, 4)
        .then((r) => setSuggestions(r.results))
        .catch(() => setSuggestions([]));
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text, focused]);

  // B3: results of the submitted query
  useEffect(() => {
    const q = submitted.trim();
    if (!q) {
      setResults({ kind: 'idle' });
      return;
    }
    const controller = new AbortController();
    setResults({ kind: 'loading' });
    setFilters({});
    searchDrugs(q, controller.signal, 30)
      .then((r) => setResults({ kind: 'done', hits: r.results }))
      .catch((e: unknown) => {
        if ((e as Error).name !== 'AbortError') setResults({ kind: 'error', detail: friendlyError(e) });
      });
    return () => controller.abort();
  }, [submitted]);

  const submit = (q: string) => {
    const query = q.trim();
    if (!query) return;
    setText(query);
    setSubmitted(query);
    setFocused(false);
    input.current?.blur();
    add({ ar: query, en: null, register: null, query });
  };

  const openDrug = (hit: SearchHit) => {
    if (params.compareWith) {
      if (params.compareWith === hit.register_number) return; // a drug is not compared with itself
      router.replace({ pathname: '/compare', params: { a: params.compareWith, b: hit.register_number } });
      return;
    }
    add({ ar: displayName(hit), en: hit.trade_name_en, register: hit.register_number, query: text });
    router.push({ pathname: '/drug/[register]', params: { register: hit.register_number } });
  };

  const hits = results.kind === 'done' ? results.hits : [];
  const shown = useMemo(
    () => hits.filter((h) => (Object.keys(filters) as FilterKey[]).every((k) => valueOf(h, k) === filters[k])),
    [hits, filters],
  );
  const suggestion = results.kind === 'done' ? didYouMean(hits, submitted) : null;
  const typing = focused && text.trim().length > 0;
  const showRecents = focused && !text.trim();

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {/* search bar: back arrow on the right, field, clear, mic and camera on the left */}
      <View style={styles.bar}>
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))}
          style={styles.iconBtn}
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <View
          style={[
            styles.field,
            { backgroundColor: c.sf },
            focused ? { borderWidth: 1.5, borderColor: c.pr } : cardShadow,
          ]}
        >
          <TextInput
            ref={input}
            value={text}
            onChangeText={setText}
            onFocus={() => setFocused(true)}
            onSubmitEditing={() => submit(text)}
            autoFocus={params.focus === '1' || !params.q}
            placeholder="ابحث بالاسم أو المادة الفعالة"
            placeholderTextColor={c.ink2}
            returnKeyType="search"
            autoCorrect={false}
            autoCapitalize="none"
            style={[styles.input, { color: c.ink, fontFamily: fonts.ar[400] }]}
          />
          {text ? (
            <Pressable onPress={() => { setText(''); input.current?.focus(); }} style={styles.smallBtn} accessibilityLabel="مسح">
              <XCircleIcon size={20} color={c.ink2} />
            </Pressable>
          ) : null}
          <Pressable onPress={() => router.push('/voice')} style={styles.smallBtn} accessibilityLabel="بحث صوتي">
            <MicrophoneIcon size={22} color={c.ink} />
          </Pressable>
          <Pressable onPress={() => router.push('/scan')} style={styles.smallBtn} accessibilityLabel="مسح علبة الدواء">
            <CameraIcon size={22} color={c.ink} />
          </Pressable>
        </View>
      </View>
      <DisclaimerBar />
      {params.compareWith ? (
        <View style={{ paddingHorizontal: 16, paddingVertical: 8 }}>
          <T size={13.5} weight={600} color={c.pr}>
            اختر الدواء الثاني للمقارنة
          </T>
        </View>
      ) : null}

      {typing ? (
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.suggest}>
          {suggestions.length ? (
            <T size={12.5} color={c.ink2}>
              اقتراحات
            </T>
          ) : null}
          {suggestions.map((s) => (
            <Pressable key={s.register_number} onPress={() => openDrug(s)} style={styles.suggestRow}>
              <MagnifyingGlassIcon size={18} color={c.ink2} />
              <T style={{ flex: 1 }} numberOfLines={1}>
                {displayName(s)}
              </T>
              <T size={13} color={c.ink2} latin numberOfLines={1} style={{ maxWidth: '45%' }}>
                {s.ingredients.length === 1 ? s.ingredients[0] : s.trade_name_en ?? ''}
              </T>
            </Pressable>
          ))}
          <RecentList onPick={(q) => submit(q)} />
        </ScrollView>
      ) : showRecents ? (
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={styles.suggest}>
          <RecentList onPick={(q) => submit(q)} />
          {!recents.length ? (
            <T size={14} color={c.ink2}>
              اكتب اسم الدواء بالعربي أو الإنجليزي، حتى لو فيه خطأ إملائي.
            </T>
          ) : null}
        </ScrollView>
      ) : (
        <>
          {suggestion ? (
            <Row gap={4} style={{ paddingHorizontal: 16, paddingTop: 12 }}>
              <T size={15}>هل تقصد:</T>
              <Pressable onPress={() => submit(suggestion)}>
                <T size={15} weight={700} color={c.pr} style={{ textDecorationLine: 'underline' }}>
                  {suggestion}
                </T>
              </Pressable>
              <T size={15}>؟</T>
            </Row>
          ) : null}
          {results.kind === 'done' && hits.length > 0 ? (
            <View style={styles.chips}>
              {FILTERS.map((f) => {
                const selected = filters[f.key];
                return (
                  <Pressable
                    key={f.key}
                    onPress={() => setOpenFilter(f.key)}
                    style={[
                      styles.chip,
                      { backgroundColor: selected ? c.prs : c.sf, borderColor: selected ? c.pr : c.ln },
                    ]}
                  >
                    <T size={14} color={selected ? c.pr : c.ink} numberOfLines={1}>
                      {selected ?? f.label}
                    </T>
                    <CaretDownIcon size={14} color={c.ink} />
                  </Pressable>
                );
              })}
            </View>
          ) : null}
          {results.kind === 'loading' && <Loading />}
          {results.kind === 'error' && <Message title="حصلت مشكلة" detail={results.detail} />}
          {results.kind === 'idle' && <Message title="اكتب اسم الدواء" />}
          {results.kind === 'done' && hits.length === 0 && (
            <Message title="ما فيه نتائج" detail="جرّب الاسم العلمي أو اكتبه بطريقة ثانية." />
          )}
          {results.kind === 'done' && hits.length > 0 && (
            <FlatList
              data={shown}
              keyExtractor={(h) => h.register_number}
              keyboardShouldPersistTaps="handled"
              contentContainerStyle={styles.list}
              ListHeaderComponent={
                <Row style={{ justifyContent: 'space-between', paddingBottom: 4 }}>
                  <T size={14} color={c.ink2}>
                    {shown.length} نتيجة
                  </T>
                  <Row gap={4}>
                    <T size={14} color={c.ink2}>
                      الترتيب: الصلة
                    </T>
                    <SortDescendingIcon size={16} color={c.ink2} />
                  </Row>
                </Row>
              }
              renderItem={({ item }) => <ResultCard hit={item} onPress={() => openDrug(item)} />}
            />
          )}
        </>
      )}

      <Modal visible={openFilter !== null} transparent animationType="slide" onRequestClose={() => setOpenFilter(null)}>
        <Pressable style={styles.backdrop} onPress={() => setOpenFilter(null)} />
        <View style={[styles.sheet, { backgroundColor: c.sf }]}>
          <T size={18} weight={700}>
            {FILTERS.find((f) => f.key === openFilter)?.label}
          </T>
          <ScrollView style={{ maxHeight: 360 }}>
            {openFilter
              ? [null, ...Array.from(new Set(hits.map((h) => valueOf(h, openFilter)).filter((v): v is string => !!v)))].map(
                  (value) => (
                    <Pressable
                      key={value ?? 'all'}
                      onPress={() => {
                        setFilters((f) => {
                          const next = { ...f };
                          if (value === null) delete next[openFilter];
                          else next[openFilter] = value;
                          return next;
                        });
                        setOpenFilter(null);
                      }}
                      style={styles.sheetRow}
                    >
                      <T weight={filters[openFilter] === value || (!filters[openFilter] && value === null) ? 700 : 400}>
                        {value ?? 'الكل'}
                      </T>
                    </Pressable>
                  ),
                )
              : null}
          </ScrollView>
        </View>
      </Modal>
    </SafeAreaView>
  );

  function RecentList({ onPick }: { onPick: (q: string) => void }) {
    if (!recents.length) return null;
    return (
      <>
        <T size={12.5} color={c.ink2} style={{ marginTop: 8 }}>
          عمليات بحث سابقة
        </T>
        {recents.map((r) => (
          <View key={r.register ?? r.query} style={styles.suggestRow}>
            <Pressable
              onPress={() =>
                r.register
                  ? router.push({ pathname: '/drug/[register]', params: { register: r.register } })
                  : onPick(r.query)
              }
              style={{ flex: 1, flexDirection: 'row-reverse', alignItems: 'center', gap: 12 }}
            >
              <ClockCounterClockwiseIcon size={18} color={c.ink2} />
              <T style={{ flex: 1 }} numberOfLines={1}>
                {r.ar}
              </T>
            </Pressable>
            <Pressable onPress={() => remove(r)} style={styles.smallBtn} accessibilityLabel="حذف من السجل">
              <XIcon size={16} color={c.ink2} />
            </Pressable>
          </View>
        ))}
      </>
    );
  }
}

function ResultCard({ hit, onPress }: { hit: SearchHit; onPress: () => void }) {
  const { c } = useTheme();
  const meta = [hit.dosage_form_ar ?? hit.dosage_form_en, hit.marketing_company].filter(Boolean).join(' · ');
  return (
    <Pressable onPress={onPress} style={({ pressed }) => pressed && { opacity: 0.75 }}>
      <Card>
        <Row gap={12} style={{ alignItems: 'flex-start' }}>
          <DrugPicture register={hit.register_number} />
          <View style={{ flex: 1, gap: 4 }}>
            <T size={18} weight={700}>
              {displayName(hit)}
            </T>
            {hit.trade_name_en && hit.trade_name_ar ? (
              <T size={14} color={c.ink2} latin align="right">
                {hit.trade_name_en}
              </T>
            ) : null}
            <T size={15} weight={700} latin align="right">
              {hit.ingredients.join(' + ')}
            </T>
            <T size={14} color={c.ink2}>
              {meta}
            </T>
            {hit.listing_status !== 'listed' ? <Pill label="غير مدرج حاليًا" tone="rd" /> : null}
          </View>
        </Row>
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  field: {
    flex: 1,
    minHeight: 52,
    borderRadius: radius.lg,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    paddingHorizontal: 6,
  },
  input: { flex: 1, minWidth: 0, width: 0, fontSize: 17, textAlign: 'right', writingDirection: 'rtl', paddingHorizontal: 10, minHeight: 48 },
  smallBtn: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  suggest: { paddingHorizontal: 16, paddingVertical: 10 },
  suggestRow: { minHeight: 50, flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  chips: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16, paddingVertical: 12 },
  chip: {
    minHeight: 44,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    borderWidth: 1,
  },
  list: { paddingHorizontal: 16, paddingBottom: 24, gap: 12 },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.35)' },
  sheet: { borderTopLeftRadius: radius.sheet, borderTopRightRadius: radius.sheet, padding: 20, gap: 8, paddingBottom: 34 },
  sheetRow: { minHeight: 48, justifyContent: 'center' },
});
