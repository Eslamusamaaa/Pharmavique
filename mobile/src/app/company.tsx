// Company screen: who sells an ingredient (market map), thin and missing strengths and forms
// (gaps), and what changed lately (radar). Registry rows only: there are no sales or demand figures.
import { router } from 'expo-router';
import { ArrowRightIcon } from 'phosphor-react-native';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  arabicCompanyError,
  getGaps,
  getMarketMap,
  getRadar,
  type Gaps,
  type MarketMap,
  type PriceRange,
  type Radar,
  type RadarItem,
} from '@/api/company';
import { searchIngredients } from '@/api/me';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { radius, useTheme } from '@/theme';

type Tab = 'market' | 'gaps' | 'radar';

const TABS: { key: Tab; label: string }[] = [
  { key: 'market', label: 'خريطة السوق' },
  { key: 'gaps', label: 'الفجوات' },
  { key: 'radar', label: 'الرادار' },
];

const KIND_AR: Record<RadarItem['kind'], string> = {
  added: 'دواء جديد في السجل',
  relisted: 'رجع للسجل',
  withdrawn: 'انسحب من السجل',
  price_changed: 'تغيّر السعر',
};

const BASIS_AR: Record<string, string> = {
  source_stated: 'العملة مذكورة في المصدر',
  owner_assumption: 'العملة افتراض منّا',
  unconfirmed: 'العملة غير مؤكدة',
};

// The notes under each tab, in the app's language (the API's own notes are in English).
const NOTE_MARKET =
  'الأرقام من سجل الهيئة (SFDA) حسب آخر تحديث، وما هي مبيعات ولا مخزون ولا طلب. الأسعار أسعار العبوة المسجّلة، والعبوات تختلف.';
const NOTE_GAPS =
  'الخانة الضعيفة فيها شركات مسجّلة قليلة. الخانة الناقصة تركيز وشكل موجودين لهذي المادة لكن ما اجتمعوا أبد، وممكن ما يكون لها معنى طبي أو نظامي. وما تقول شي عن الطلب.';
const NOTE_RADAR = 'التغييرات اللي انرصدت في السجل من أول تحديث للبيانات. تبيّن وش تغيّر، مو ليش.';

/** "15.100000" from the API reads as "15.10". */
function money(amount: string | number): string {
  const n = Number(amount);
  return Number.isFinite(n) ? n.toFixed(2) : String(amount);
}

function priceText(r: PriceRange): string {
  const range = r.lowest === r.highest ? money(r.lowest) : `${money(r.lowest)} – ${money(r.highest)}`;
  return `${range} ${r.currency_code ?? ''} (${r.count} دواء) · ${BASIS_AR[r.currency_basis] ?? r.currency_basis}`;
}

export default function Company() {
  const { c } = useTheme();
  const { account } = useAccount();
  const [tab, setTab] = useState<Tab>('market');
  const [typed, setTyped] = useState('');
  const [ingredient, setIngredient] = useState('');
  const [options, setOptions] = useState<string[]>([]);
  const [market, setMarket] = useState<MarketMap | null>(null);
  const [gaps, setGaps] = useState<Gaps | null>(null);
  const [radar, setRadar] = useState<Radar | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typed.trim().length < 2) {
      setOptions([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => searchIngredients(typed.trim(), controller.signal).then(setOptions), 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [typed]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (tab === 'market' && ingredient) setMarket(await getMarketMap(ingredient));
      else if (tab === 'gaps' && ingredient) setGaps(await getGaps(ingredient));
      else if (tab === 'radar') setRadar(await getRadar(ingredient || null, 30));
    } catch (e) {
      setError(arabicCompanyError(e));
    } finally {
      setLoading(false);
    }
  }, [tab, ingredient]);

  useEffect(() => {
    if (account) load();
  }, [account, load]);

  const header = (
    <View style={styles.topBar}>
      <Pressable
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/account'))}
        style={styles.iconBtn}
        accessibilityLabel="رجوع"
      >
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        شاشة الشركات
      </T>
    </View>
  );

  if (account === null) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Message
          title="هذي الشاشة لحسابات الشركات"
          detail="سجّل الدخول بحساب شركة أو مخزن أدوية."
          action={
            <Pressable onPress={() => router.push('/sign-in')} style={[styles.main, { backgroundColor: c.pr }]}>
              <T weight={700} color={c.prt}>
                تسجيل الدخول
              </T>
            </Pressable>
          }
        />
      </SafeAreaView>
    );
  }

  const choose = (name: string) => {
    setTyped('');
    setOptions([]);
    setIngredient(name);
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Row gap={8}>
          {TABS.map((t) => (
            <Pressable
              key={t.key}
              onPress={() => setTab(t.key)}
              style={[styles.tab, { borderColor: c.pr, backgroundColor: tab === t.key ? c.pr : 'transparent' }]}
              accessibilityRole="button"
            >
              <T size={14} weight={600} color={tab === t.key ? c.prt : c.pr}>
                {t.label}
              </T>
            </Pressable>
          ))}
        </Row>

        <TextInput
          value={typed}
          onChangeText={setTyped}
          placeholder={ingredient ? `المادة الفعالة: ${ingredient}` : 'اكتب أول حروف المادة الفعالة (بالإنجليزي)'}
          placeholderTextColor={c.ink2}
          autoCapitalize="characters"
          autoCorrect={false}
          style={[styles.input, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }]}
        />
        {options.map((name) => (
          <Pressable key={name} onPress={() => choose(name)} style={[styles.option, { borderColor: c.ink2 }]}>
            <T latin align="left">
              {name}
            </T>
          </Pressable>
        ))}

        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}
        {loading ? <Loading /> : null}
        {!ingredient && tab !== 'radar' ? (
          <T size={14} color={c.ink2}>
            اختر مادة فعالة عشان تشوف الأرقام.
          </T>
        ) : null}

        {tab === 'market' && market && ingredient ? <MarketView data={market} /> : null}
        {tab === 'gaps' && gaps && ingredient ? <GapsView data={gaps} /> : null}
        {tab === 'radar' && radar ? <RadarView data={radar} /> : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function MarketView({ data }: { data: MarketMap }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 12 }}>
      <Card style={{ gap: 4 }}>
        <T size={13} color={c.ink2} latin align="left">
          {data.ingredient}
        </T>
        <T weight={700}>
          {data.listed} دواء مسجّل · {data.makers} شركة · {data.withdrawn} مسحوب
        </T>
      </Card>
      {data.top_makers.length > 0 ? (
        <View style={{ gap: 6 }}>
          <H2>أكثر الشركات تسجيلًا</H2>
          {data.top_makers.map((m) => (
            <Row key={m.name} style={{ justifyContent: 'space-between' }}>
              <T size={14} latin style={{ flex: 1 }} align="left">
                {m.name}
              </T>
              <T size={14} weight={700}>
                {m.count}
              </T>
            </Row>
          ))}
        </View>
      ) : null}
      {data.groups.map((g) => (
        <Card key={g.ingredients.join('+')} style={{ gap: 6 }}>
          <T weight={700} latin align="left">
            {g.ingredients.join(' + ')}
          </T>
          <T size={14}>
            {g.listed} مسجّل · {g.makers} شركة · {g.withdrawn} مسحوب
          </T>
          {g.price_ranges.map((r) => (
            <T key={`${r.currency_code}-${r.currency_basis}`} size={13} color={c.ink2}>
              السعر المسجّل للعبوة: {priceText(r)}
            </T>
          ))}
          <T size={13} color={c.ink2}>
            الأشكال: {g.forms.map((f) => `${f.name} (${f.count})`).join('، ') || 'غير مذكور'}
          </T>
          <T size={13} color={c.ink2}>
            التركيزات: {g.strengths.map((s) => `${s.name} (${s.count})`).join('، ') || 'غير مذكور'}
          </T>
        </Card>
      ))}
      <T size={12.5} color={c.ink2}>
        {NOTE_MARKET}
      </T>
    </View>
  );
}

function GapsView({ data }: { data: Gaps }) {
  const { c } = useTheme();
  const thin = data.cells.filter((x) => x.thin);
  return (
    <View style={{ gap: 12 }}>
      <H2>تركيزات وأشكال قليلة الشركات</H2>
      {thin.length === 0 ? (
        <T size={14} color={c.ink2}>
          ما فيه تركيز وشكل عدد شركاته {data.thin_at} أو أقل.
        </T>
      ) : (
        thin.slice(0, 40).map((x) => (
          <Card key={`${x.strength}-${x.dosage_form}`} style={{ gap: 4 }}>
            <T weight={700} latin align="left">
              {x.strength}
            </T>
            <T size={14} latin align="left">
              {x.dosage_form}
            </T>
            <Pill tone="wn" label={`${x.makers} شركة · ${x.products} دواء`} />
          </Card>
        ))
      )}
      {data.missing.length > 0 ? (
        <View style={{ gap: 6 }}>
          <H2>تركيز وشكل موجودان لكن ليسا معًا</H2>
          {data.missing.slice(0, 40).map((m) => (
            <T key={`${m.strength}-${m.dosage_form}`} size={13.5} latin align="left">
              {m.strength} · {m.dosage_form}
            </T>
          ))}
        </View>
      ) : null}
      <T size={12.5} color={c.ink2}>
        {NOTE_GAPS}
      </T>
    </View>
  );
}

function RadarView({ data }: { data: Radar }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 10 }}>
      <H2>آخر {data.days} يوم</H2>
      {data.items.length === 0 ? (
        <T size={14} color={c.ink2}>
          ما فيه تغييرات مسجّلة للحين. الرادار يبدأ العدّ من أول مرة انبنت فيها البيانات.
        </T>
      ) : (
        data.items.map((i) => (
          <Pressable
            key={`${i.register_number}-${i.occurred_at}-${i.kind}`}
            onPress={() => router.push({ pathname: '/drug/[register]', params: { register: i.register_number } })}
          >
            <Card style={{ gap: 4 }}>
              <T weight={700} latin align="left">
                {i.trade_name_en ?? i.trade_name_ar ?? i.register_number}
              </T>
              <T size={14}>
                {KIND_AR[i.kind]}
                {i.kind === 'price_changed' && i.old_price && i.new_price
                  ? ` · من ${money(i.old_price)} إلى ${money(i.new_price)} ${i.currency_code ?? ''}`
                  : ''}
              </T>
              {i.marketing_company ? (
                <T size={13} color={c.ink2} latin align="left">
                  {i.marketing_company}
                </T>
              ) : null}
              <T size={12} color={c.ink2}>
                {new Date(i.occurred_at).toLocaleDateString('ar-EG')}
              </T>
            </Card>
          </Pressable>
        ))
      )}
      <T size={12.5} color={c.ink2}>
        {NOTE_RADAR}
      </T>
    </View>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14, paddingBottom: 80 },
  main: { minHeight: 48, paddingHorizontal: 24, borderRadius: radius.md, justifyContent: 'center' },
  tab: { minHeight: 40, paddingHorizontal: 14, borderRadius: radius.pill, borderWidth: 1.5, justifyContent: 'center' },
  input: { minHeight: 48, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 15, textAlign: 'left' },
  option: { minHeight: 44, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, justifyContent: 'center' },
});
