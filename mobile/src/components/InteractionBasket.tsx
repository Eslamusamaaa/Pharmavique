// Drug interaction check: add medicines, see what a source records between them.
// Informational only: a finding is a source's statement with its severity, never advice, and
// "nothing found" is never "safe" (the pharmacist or doctor decides).
import { router } from 'expo-router';
import { ArrowRightIcon, MagnifyingGlassIcon, WarningIcon, XIcon } from 'phosphor-react-native';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  checkInteractions,
  displayName,
  friendlyError,
  searchDrugs,
  type InteractionCheck,
  type InteractionFinding,
  type SearchHit,
} from '@/api/client';
import { DrugPicture } from '@/components/DrugPicture';
import { Card, DisclaimerBar, Loading, Pill, Row, T } from '@/components/ui';
import { MAX_ITEMS, useSavedBasket, type BasketItem } from '@/state/basket';
import { fonts, radius, useTheme } from '@/theme';

const SEVERITY: Record<string, { label: string; tone: 'rd' | 'wn' | 'neutral' | 'muted' }> = {
  major: { label: 'تداخل شديد', tone: 'rd' },
  moderate: { label: 'تداخل متوسط', tone: 'wn' },
  minor: { label: 'تداخل بسيط', tone: 'neutral' },
  unknown: { label: 'تداخل مسجّل بدون تقييم', tone: 'muted' },
};

type Check = { kind: 'idle' } | { kind: 'loading' } | { kind: 'done'; data: InteractionCheck } | { kind: 'error'; detail: string };

export function InteractionBasket({
  title,
  intro,
  persist,
  initialItems,
}: {
  title: string;
  intro: string;
  persist: boolean;
  initialItems?: BasketItem[];
}) {
  const { c } = useTheme();
  const saved = useSavedBasket();
  const [local, setLocal] = useState<BasketItem[]>(initialItems ?? []);
  const items = persist ? saved.items : local;
  const setItems = persist ? saved.set : setLocal;

  const [text, setText] = useState('');
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [check, setCheck] = useState<Check>({ kind: 'idle' });
  const registers = useMemo(() => items.map((i) => i.register), [items]);

  // search as the person types
  useEffect(() => {
    const q = text.trim();
    if (q.length < 2) {
      setHits([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      searchDrugs(q, controller.signal, 6)
        .then((r) => setHits(r.results))
        .catch(() => setHits([]));
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [text]);

  // check whenever the list changes and holds at least two medicines
  useEffect(() => {
    if (registers.length < 2) {
      setCheck({ kind: 'idle' });
      return;
    }
    const controller = new AbortController();
    setCheck({ kind: 'loading' });
    checkInteractions(registers, controller.signal)
      .then((data) => setCheck({ kind: 'done', data }))
      .catch((e: unknown) => {
        if ((e as Error).name !== 'AbortError') setCheck({ kind: 'error', detail: friendlyError(e) });
      });
    return () => controller.abort();
  }, [registers]);

  const add = (hit: SearchHit) => {
    if (items.length >= MAX_ITEMS || items.some((i) => i.register === hit.register_number)) return;
    setItems([...items, { register: hit.register_number, ar: hit.trade_name_ar, en: hit.trade_name_en }]);
    setText('');
    setHits([]);
  };
  const remove = (register: string) => setItems(items.filter((i) => i.register !== register));

  const names = useMemo(() => {
    const map = new Map<string, string>();
    items.forEach((i) => map.set(i.register, i.ar || i.en || i.register));
    return map;
  }, [items]);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.topBar}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))} style={styles.iconBtn} accessibilityLabel="رجوع">
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          {title}
        </T>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled" keyboardDismissMode="on-drag">
        <T size={14} color={c.ink2}>
          {intro}
        </T>

        <View style={[styles.search, { backgroundColor: c.sf, borderColor: c.ln }]}>
          <MagnifyingGlassIcon size={20} color={c.ink2} />
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="ابحث عن دواء لإضافته"
            placeholderTextColor={c.ink2}
            style={{ flex: 1, color: c.ink, fontFamily: fonts.ar[400], fontSize: 16, textAlign: 'right', paddingVertical: 10 }}
            returnKeyType="search"
          />
        </View>
        {hits.map((h) => (
          <Pressable key={h.register_number} onPress={() => add(h)}>
            <Card style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 10 }}>
              <DrugPicture register={h.register_number} size={44} />
              <View style={{ flex: 1 }}>
                <T weight={600} numberOfLines={1}>
                  {displayName(h)}
                </T>
                <T size={12.5} color={c.ink2} latin align="right" numberOfLines={1}>
                  {h.ingredients.join(' + ')}
                </T>
              </View>
              <T size={13} weight={700} color={c.pr}>
                إضافة
              </T>
            </Card>
          </Pressable>
        ))}

        <T size={18} weight={700}>
          الأدوية ({items.length})
        </T>
        {items.length === 0 ? (
          <T size={14} color={c.ink2}>
            أضف دوائين على الأقل ليظهر الفحص.
          </T>
        ) : (
          <Row gap={8} style={{ flexWrap: 'wrap' }}>
            {items.map((i) => (
              <Pressable key={i.register} onPress={() => remove(i.register)} style={[styles.chip, { backgroundColor: c.prs }]} accessibilityLabel={`حذف ${i.ar || i.en || ''}`}>
                <T size={14} weight={600} numberOfLines={1} style={{ maxWidth: 220 }}>
                  {i.ar || i.en || i.register}
                </T>
                <XIcon size={14} color={c.ink2} />
              </Pressable>
            ))}
          </Row>
        )}

        {check.kind === 'loading' ? <Loading /> : null}
        {check.kind === 'error' ? <T color={c.rd}>{check.detail}</T> : null}
        {check.kind === 'done' ? <Results data={check.data} names={names} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function Results({ data, names }: { data: InteractionCheck; names: Map<string, string> }) {
  const { c } = useTheme();
  const interactions = data.findings.filter((f) => f.kind === 'interaction');
  const duplicates = data.findings.filter((f) => f.kind === 'duplicate_ingredient');
  const name = (register: string) => names.get(register) ?? register;

  return (
    <View style={{ gap: 12 }}>
      <T size={18} weight={700}>
        نتيجة الفحص
      </T>
      {interactions.length === 0 ? (
        <Card style={{ gap: 6 }}>
          <T weight={600}>لا يوجد تداخل مسجّل في المصدر بين هذه الأدوية.</T>
          <T size={13} color={c.ink2}>
            هذا لا يعني أن الجمع بينها آمن. اسأل الصيدلي أو الطبيب.
          </T>
        </Card>
      ) : null}
      {interactions.map((f) => (
        <FindingCard key={`${f.registers.join('-')}-${f.ingredients.join('-')}`} finding={f} name={name} />
      ))}
      {duplicates.length > 0 ? <T weight={700}>مواد فعالة مكررة</T> : null}
      {duplicates.map((f) => (
        <FindingCard key={`d-${f.registers.join('-')}`} finding={f} name={name} />
      ))}
      {data.unmatched.length > 0 ? (
        <Card style={{ gap: 6, backgroundColor: c.wns }}>
          <Row gap={6}>
            <WarningIcon size={18} color={c.wn} weight="fill" />
            <T weight={700} color={c.wn}>
              مواد لم يستطع المصدر تقييمها
            </T>
          </Row>
          {data.unmatched.map((u) => (
            <T key={`${u.register_number}-${u.ingredient}`} size={13} latin align="left">
              {name(u.register_number)} · {u.ingredient}
            </T>
          ))}
        </Card>
      ) : null}
      {data.unknown_registers.length > 0 ? (
        <T size={13} color={c.rd}>
          أرقام تسجيل غير موجودة في السجل: {data.unknown_registers.join('، ')}
        </T>
      ) : null}
      <T size={12.5} color={c.ink2}>
        {data.note}
      </T>
    </View>
  );
}

function FindingCard({ finding, name }: { finding: InteractionFinding; name: (register: string) => string }) {
  const { c } = useTheme();
  const duplicate = finding.kind === 'duplicate_ingredient';
  const level = duplicate ? { label: 'مادة فعالة مكررة', tone: 'wn' as const } : SEVERITY[finding.severity ?? 'unknown'];
  return (
    <Card style={{ gap: 8 }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <Pill label={level.label} tone={level.tone} />
      </Row>
      <T weight={700}>
        {name(finding.registers[0])} + {name(finding.registers[1])}
      </T>
      <T size={13} color={c.ink2} latin align="left">
        {finding.ingredients[0]} + {finding.ingredients[1]}
      </T>
      <T size={12.5} color={c.ink2}>
        {duplicate
          ? 'نفس المادة الفعالة في الدوائين (من سجل الهيئة). اسأل الصيدلي.'
          : `المصدر: DDInter 2.0 (مصدر خارجي)، والتقييم كما يذكره المصدر. اسأل الصيدلي أو الطبيب.`}
      </T>
    </Card>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14, paddingBottom: 120 },
  search: {
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 8,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 12,
  },
  chip: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
});
