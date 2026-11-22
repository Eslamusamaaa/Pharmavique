// B8 · Drug page · mobile (pharmavique-wireframes/PvDrug.dc.html), light and dark.
import { router, useLocalSearchParams } from 'expo-router';
import {
  ArrowRightIcon,
  BookmarkSimpleIcon,
  ChatCircleDotsIcon,
  CheckCircleIcon,
  ColumnsIcon,
  DatabaseIcon,
  DotsThreeVerticalIcon,
  EqualsIcon,
  InfoIcon,
  PillIcon,
  SealCheckIcon,
  ShareNetworkIcon,
  StorefrontIcon,
  WarningIcon,
} from 'phosphor-react-native';
import { useEffect, useMemo, useState } from 'react';
import { Linking, Pressable, ScrollView, Share, StyleSheet, View } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  displayName,
  friendlyError,
  getContraindications,
  getDrugPage,
  getSameIngredient,
  getShortage,
  getSimilarNames,
  type Contraindications,
  type DrugPage,
  type Ingredient,
  type Price,
  type SameIngredient,
  type Shortage,
  type SimilarNames,
} from '@/api/client';
import { arabicMeError, getAllergyCheck, getHistoryCheck, saveMedicine, type AllergyCheck, type HistoryCheck } from '@/api/me';
import { HistoryCard } from '@/components/history-card';
import { DrugPicture } from '@/components/DrugPicture';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { cardShadow, radius, useTheme } from '@/theme';

type State = { kind: 'loading' } | { kind: 'done'; drug: DrugPage } | { kind: 'error'; detail: string };

const UNIT_AR: Record<string, string> = { mg: 'ملجم', mcg: 'ميكروجرام', g: 'جم', ml: 'مل', iu: 'وحدة دولية' };
const LEGAL_AR: Record<string, string> = { OTC: 'بدون وصفة طبية', Prescription: 'بوصفة طبية' };
const DIST_AR: Record<string, string> = { Pharmacy: 'صيدلية', Hospital: 'مستشفى' };
const PACKAGE_AR: Record<string, string> = { Blister: 'شريط', Bottle: 'زجاجة', Vial: 'فيال', Ampoule: 'أمبولة', Tube: 'أنبوب' };
const MONTHS = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر'];

function arabicDate(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function unitAr(unit: string | null): string {
  if (!unit) return '';
  return unit
    .split('/')
    .map((u) => UNIT_AR[u.trim().toLowerCase()] ?? u)
    .join(' / ');
}

function currencyLabel(price: Price): string {
  if (price.currency_code === 'SAR') return price.currency_basis === 'source_stated' ? 'ريال سعودي' : 'ريال سعودي (افتراضي)';
  return price.currency_code ? `${price.currency_code} (غير مؤكد)` : 'عملة غير مذكورة في المصدر';
}

export default function DrugScreen() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const { register } = useLocalSearchParams<{ register: string }>();
  const [state, setState] = useState<State>({ kind: 'loading' });
  const [same, setSame] = useState<SameIngredient[] | null>(null);
  const [contra, setContra] = useState<Contraindications | null>(null);
  const [shortage, setShortage] = useState<Shortage | null>(null);
  const [similar, setSimilar] = useState<SimilarNames | null>(null);
  const { account } = useAccount();
  const [allergy, setAllergy] = useState<AllergyCheck | null>(null);
  const [history, setHistory] = useState<HistoryCheck | null>(null);
  const [saveNote, setSaveNote] = useState<string | null>(null);
  const [sort, setSort] = useState<'price' | 'name'>('price');

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: 'loading' });
    getDrugPage(register, controller.signal)
      .then((drug) => setState({ kind: 'done', drug }))
      .catch((e: unknown) => {
        if ((e as Error).name !== 'AbortError') setState({ kind: 'error', detail: friendlyError(e) });
      });
    getSameIngredient(register, controller.signal)
      .then((r) => setSame(r.results))
      .catch(() => setSame([]));
    getContraindications(register, controller.signal)
      .then(setContra)
      .catch(() => setContra(null));
    getShortage(register, controller.signal)
      .then(setShortage)
      .catch(() => setShortage(null));
    getSimilarNames(register, controller.signal)
      .then(setSimilar)
      .catch(() => setSimilar(null));
    return () => controller.abort();
  }, [register]);

  useEffect(() => {
    if (!account) {
      setAllergy(null);
      return;
    }
    const controller = new AbortController();
    getAllergyCheck(register, controller.signal)
      .then(setAllergy)
      .catch(() => setAllergy(null));
    return () => controller.abort();
  }, [register, account]);

  useEffect(() => {
    if (!account) {
      setHistory(null);
      return;
    }
    const controller = new AbortController();
    getHistoryCheck(register, controller.signal)
      .then(setHistory)
      .catch(() => setHistory(null));
    return () => controller.abort();
  }, [register, account]);

  const save = () => {
    if (!account) {
      router.push('/sign-in');
      return;
    }
    saveMedicine(register)
      .then(() => setSaveNote('انحفظ في قائمتي'))
      .catch((e: unknown) => setSaveNote(arabicMeError(e)));
  };

  const shortageSet = useMemo(
    () => new Set((shortage?.substitutes ?? []).filter((s) => s.also_on_shortage_list).map((s) => s.register_number)),
    [shortage],
  );

  const sortedSame = useMemo(() => {
    if (!same) return [];
    // Wireframe note 6: different ingredient sets are never listed (the API only returns the same set).
    const rows = [...same];
    if (sort === 'name') rows.sort((a, b) => displayName(a).localeCompare(displayName(b), 'ar'));
    return rows;
  }, [same, sort]);

  const header = (
    <View style={styles.topBar}>
      <Pressable
        onPress={() => (router.canGoBack() ? router.back() : router.navigate('/search'))}
        style={styles.iconBtn}
        accessibilityLabel="رجوع"
      >
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        تفاصيل الدواء
      </T>
      <View style={styles.iconBtn}>
        <DotsThreeVerticalIcon size={24} color={c.ink} />
      </View>
    </View>
  );

  if (state.kind !== 'done') {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <DisclaimerBar />
        {state.kind === 'loading' ? <Loading /> : <Message title="ما قدرت أجيب بيانات الدواء" detail={state.detail} />}
      </SafeAreaView>
    );
  }

  const d = state.drug;
  const fetched = arabicDate(d.provenance.fetched_at);
  const official = d.provenance.trust === 'official';
  const facts: { k: string; v: string | null; en?: string | null }[] = [
    { k: 'الشكل الدوائي', v: d.dosage_form_ar, en: d.dosage_form_en },
    { k: 'طريقة الاستخدام', v: d.route_ar, en: d.route_en },
    {
      k: 'العبوة',
      v: [d.package_type ? PACKAGE_AR[d.package_type] ?? d.package_type : null, d.package_size ? `${d.package_size}` : null]
        .filter(Boolean)
        .join('، ') || null,
    },
    { k: 'رمز ATC', v: d.atc_codes.join('، ') || null },
    { k: 'الحالة النظامية', v: d.legal_status ? LEGAL_AR[d.legal_status] ?? d.legal_status : null },
    { k: 'جهة التوزيع', v: d.distribution_site ? DIST_AR[d.distribution_site] ?? d.distribution_site : null },
    // The source states no unit for shelf life, so none is added (never guessed).
    { k: 'مدة الصلاحية', v: d.shelf_life },
    { k: 'التخزين', v: d.storage_ar, en: d.storage_ar ? null : d.storage_en },
  ];

  const share = () =>
    Share.share({
      message: `${displayName(d)}${d.trade_name_en ? ` (${d.trade_name_en})` : ''} · رقم التسجيل ${d.register_number} · المصدر: SFDA`,
    }).catch(() => undefined);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={[styles.content, { paddingBottom: 120 + insets.bottom }]}>
        {/* name, register number, trust badge, fetched date and source, status chips */}
        <View style={{ gap: 6 }}>
          <View style={{ alignItems: 'center', marginBottom: 8 }}>
            <DrugPicture register={d.register_number} size={168} />
          </View>
          <T size={28} weight={700} style={{ lineHeight: 36 }}>
            {displayName(d)}
          </T>
          {d.trade_name_en ? (
            <T size={15} color={c.ink2} latin align="right">
              {d.trade_name_en}
            </T>
          ) : null}
          <Row gap={4}>
            <T size={13} color={c.ink2}>
              رقم التسجيل:
            </T>
            <T size={13} weight={600} latin>
              {d.register_number}
            </T>
          </Row>
          <View style={{ gap: 6, marginTop: 8 }}>
            {official ? (
              <Pill
                tone="ok"
                label="بيانات رسمية من هيئة الغذاء والدواء"
                icon={<SealCheckIcon size={16} color={c.ok} weight="fill" />}
              />
            ) : (
              <Pill tone="wn" label="غير موثّق" icon={<WarningIcon size={16} color={c.wn} weight="fill" />} />
            )}
            <Row gap={4}>
              {fetched ? (
                <T size={12.5} color={c.ink2}>
                  جُلبت في {fetched} ·
                </T>
              ) : null}
              {d.provenance.source_ref ? (
                <Pressable onPress={() => Linking.openURL(d.provenance.source_ref as string)}>
                  <T size={12.5} weight={600} color={c.pr}>
                    المصدر
                  </T>
                </Pressable>
              ) : null}
            </Row>
          </View>
          <Row gap={8} style={{ flexWrap: 'wrap', marginTop: 4 }}>
            {d.marketing_status === 'Marketed' ? (
              <Pill label="مسوّق" icon={<StorefrontIcon size={14} color={c.ink} />} />
            ) : d.marketing_status ? (
              <Pill label={d.marketing_status} />
            ) : null}
            {d.authorization_status === 'Valid' ? (
              <Pill label="ترخيص ساري" icon={<CheckCircleIcon size={14} color={c.ink} />} />
            ) : d.authorization_status ? (
              <Pill tone="wn" label={d.authorization_status} />
            ) : null}
            {d.listing_status !== 'listed' ? <Pill tone="rd" label="غير مدرج حاليًا في السجل" /> : null}
          </Row>
        </View>

        {allergy && allergy.matches.length > 0 ? (
          <View style={[styles.banner, { borderColor: c.wn, backgroundColor: c.sf }]}>
            <Row gap={8}>
              <WarningIcon size={20} color={c.wn} weight="fill" />
              <T weight={700} style={{ flex: 1 }}>
                فيه مادة أنت مسجّل حساسية منها
              </T>
            </Row>
            {allergy.matches.map((m) => (
              <T key={`${m.allergy}-${m.ingredient}`} size={13.5}>
                الدواء فيه {m.ingredient}، وأنت مسجّل حساسية من {m.allergy}.
              </T>
            ))}
            <T size={12.5} color={c.ink2}>
              اسأل الصيدلي أو الطبيب قبل أي استخدام. {allergy.note}
            </T>
          </View>
        ) : null}

        {history && history.compared_with.length > 0 ? <HistoryCard check={history} /> : null}

        {/* SFDA's shortage list: what it says and how sure the link is. Never "switch". */}
        {shortage && shortage.status !== 'not_listed' ? (
          <View
            style={[
              styles.banner,
              { borderColor: shortage.status === 'listed_in_shortage' ? c.wn : c.ink2, backgroundColor: c.sf },
            ]}
          >
            <Row gap={8}>
              <WarningIcon size={20} color={shortage.status === 'listed_in_shortage' ? c.wn : c.ink2} weight="fill" />
              <T weight={700} style={{ flex: 1 }}>
                {shortage.status === 'listed_in_shortage'
                  ? 'الهيئة مدرجة هذا الدواء في قائمة النواقص'
                  : 'الهيئة سجّلت أن نقص هذا الدواء انحل'}
              </T>
            </Row>
            {shortage.items.some((i) => i.confidence === 'possible') ? (
              <T size={13} color={c.ink2}>
                ربط الدواء بسجل النقص محتمل ويحتاج مراجعة الصيدلي.
              </T>
            ) : null}
            {shortage.status === 'listed_in_shortage' ? (
              <T size={13} color={c.ink2}>
                المنتجات اللي بنفس المادة الفعالة تحت. الصيدلي أو الطبيب هو من يقرر إذا كان ينفع تحل محله.
              </T>
            ) : null}
            {shortage.items[0]?.source_ref ? (
              <Pressable onPress={() => Linking.openURL(shortage.items[0].source_ref)}>
                <T size={12.5} weight={600} color={c.pr}>
                  المصدر: قائمة النواقص في هيئة الغذاء والدواء
                </T>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {/* note 3: placeholder, hatched, labelled so it never reads as the product's box */}
        <View style={[styles.placeholder, { borderColor: c.ink2, backgroundColor: c.prs }]}>
          <PillIcon size={48} color={c.ink2} />
          <View style={{ backgroundColor: c.bg, borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 }}>
            <T size={13} color={c.ink2} align="center">
              صورة توضيحية للشكل الدوائي، وليست علبة الدواء
            </T>
          </View>
        </View>

        <View style={{ gap: 10 }}>
          <H2>المادة الفعالة</H2>
          {d.ingredients.map((i: Ingredient) => (
            <Card key={i.name} style={styles.ingredient}>
              <T weight={600} latin style={{ flex: 1 }} align="left">
                {i.name}
              </T>
              {i.strength ? (
                <Row gap={4} style={{ alignItems: 'baseline' }}>
                  <T size={18} weight={700} latin>
                    {i.strength}
                  </T>
                  <T size={14} weight={500} color={c.ink2}>
                    {unitAr(i.unit)}
                  </T>
                </Row>
              ) : (
                <T size={13} color={c.ink2}>
                  التركيز غير مذكور
                </T>
              )}
            </Card>
          ))}
        </View>

        <View style={{ gap: 10 }}>
          <H2>معلومات أساسية</H2>
          <View style={styles.grid}>
            {facts
              .filter((f) => f.v)
              .map((f) => (
                <View key={f.k} style={styles.fact}>
                  <T size={12.5} color={c.ink2}>
                    {f.k}
                  </T>
                  <T size={15} weight={600}>
                    {f.v}
                  </T>
                  {f.en ? (
                    <T size={12.5} color={c.ink2} latin align="right">
                      {f.en}
                    </T>
                  ) : null}
                </View>
              ))}
          </View>
        </View>

        {/* note 4: price always with the currency-assumption label; never a selling price or stock */}
        {d.price ? (
          <Card style={{ padding: 16, gap: 10 }}>
            <T size={13} color={c.ink2}>
              السعر
            </T>
            <T size={36} weight={700} latin align="right" style={{ lineHeight: 42 }}>
              {d.price.amount}
            </T>
            <Row gap={6}>
              <T size={14}>{currencyLabel(d.price)}</T>
              <InfoIcon size={20} color={c.pr} />
            </Row>
            {d.price_change ? (
              <Pill
                tone="wn"
                label={`السعر تغيّر من ${d.price_change.old_price.amount} إلى ${d.price_change.new_price.amount} في ${arabicDate(d.price_change.changed_at) ?? ''}`}
              />
            ) : null}
            <T size={12.5} color={c.ink2}>
              السعر المسجّل في الهيئة، وتاريخ الأسعار يبدأ من 16 نوفمبر 2026
            </T>
            {d.price.currency_basis !== 'source_stated' ? (
              <View style={{ backgroundColor: c.bg, borderRadius: 10, paddingVertical: 8, paddingHorizontal: 10 }}>
                <T size={12.5} color={c.ink2}>
                  العملة غير مذكورة في المصدر الرسمي وتم اعتمادها كريال سعودي
                </T>
              </View>
            ) : null}
          </Card>
        ) : null}

        {/* note 6: same active ingredient; tier labels are cautious and computed by our rules */}
        {sortedSame.length > 0 ? (
          <View style={{ gap: 12 }}>
            <View>
              <H2>منتجات تحتوي على نفس المادة الفعالة</H2>
              <T size={13} color={c.ink2}>
                {sortedSame.length} منتجات مسجلة · {sort === 'price' ? 'الأرخص أولًا' : 'حسب الاسم'}
              </T>
            </View>
            <View style={[styles.segment, { backgroundColor: c.sf }, cardShadow]}>
              {(['price', 'name'] as const).map((key) => (
                <Pressable
                  key={key}
                  onPress={() => setSort(key)}
                  style={[styles.segmentItem, sort === key && { backgroundColor: c.pr }]}
                >
                  <T size={14} weight={sort === key ? 600 : 400} color={sort === key ? c.prt : c.ink2} align="center">
                    {key === 'price' ? 'الأرخص أولًا' : 'الاسم'}
                  </T>
                </Pressable>
              ))}
            </View>
            {sortedSame.map((r) => (
              <SameRow key={r.register_number} row={r} onShortage={shortageSet.has(r.register_number)} />
            ))}
          </View>
        ) : null}

        {/* look-alike names: a prompt to double-check the name, computed from spelling and sound only */}
        {similar && similar.results.length > 0 ? (
          <View style={{ gap: 10 }}>
            <H2>أسماء متشابهة، تأكد من الاسم</H2>
            {similar.results.map((r) => (
              <Pressable
                key={r.register_number}
                onPress={() => router.push({ pathname: '/drug/[register]', params: { register: r.register_number } })}
              >
                <Card style={{ gap: 6 }}>
                  <T weight={700}>{displayName(r)}</T>
                  {r.trade_name_en ? (
                    <T size={13} color={c.ink2} latin align="right">
                      {r.trade_name_en}
                    </T>
                  ) : null}
                  <Pill
                    tone={r.same_ingredients ? 'neutral' : 'wn'}
                    label={r.same_ingredients ? 'نفس المادة الفعالة' : 'مادة فعالة مختلفة'}
                  />
                </Card>
              </Pressable>
            ))}
            <T size={12.5} color={c.ink2}>
              هذي الأسماء متشابهة في الكتابة أو النطق. تأكد من اسم الدواء على العلبة أو الوصفة. القائمة محسوبة من الأسماء فقط وللحين ما راجعها صيدلي.
              {similar.hidden_weaker ? ` فيه ${similar.hidden_weaker} أسماء ثانية أقل تشابهًا غير معروضة.` : ''}
            </T>
          </View>
        ) : null}

        {/* contraindications recorded in drug labels (MeDIC): a source's statement, never advice */}
        {contra && contra.items.length > 0 ? (
          <View style={{ gap: 10 }}>
            <H2>حالات لا يُستخدم معها الدواء حسب نشرات الدواء</H2>
            <Row gap={8} style={{ flexWrap: 'wrap' }}>
              {Array.from(new Set(contra.items.map((i) => i.disease))).map((disease) => (
                <Pill key={disease} tone="wn" label={disease} />
              ))}
            </Row>
            <T size={12.5} color={c.ink2}>
              المصدر: MeDIC (نشرات الدواء الحكومية، مصدر خارجي). {contra.note}
            </T>
          </View>
        ) : null}

        <View style={{ gap: 10 }}>
          <H2>الشركة والمصنّعون</H2>
          {d.marketing_company ? (
            <View>
              <T size={13} color={c.ink2}>
                الشركة المسوّقة
              </T>
              <T size={15} weight={600}>
                {d.marketing_company}
                {d.marketing_company_country ? ` · ${d.marketing_company_country}` : ''}
              </T>
            </View>
          ) : null}
          {d.manufacturers.length ? (
            <View>
              <T size={13} color={c.ink2}>
                المصنّعون
              </T>
              {d.manufacturers.map((m) => (
                <T key={m.name} size={14}>
                  {m.name}
                  {m.country ? ` · ${m.country}` : ''}
                </T>
              ))}
            </View>
          ) : null}
        </View>

        <View style={{ gap: 6 }}>
          <Pressable
            onPress={() =>
              router.push({ pathname: '/assistant', params: { register: d.register_number, name: displayName(d) } })
            }
            style={styles.link}
          >
            <ChatCircleDotsIcon size={18} color={c.pr} />
            <T size={14} weight={600} color={c.pr}>
              اسأل المساعد عن هذا الدواء
            </T>
          </Pressable>
          {d.provenance.source_ref ? (
            <Pressable onPress={() => Linking.openURL(d.provenance.source_ref as string)} style={styles.link}>
              <DatabaseIcon size={18} color={c.pr} />
              <T size={14} weight={600} color={c.pr}>
                عن البيانات
              </T>
            </Pressable>
          ) : null}
        </View>
      </ScrollView>

      {/* note 8: actions are save / compare / share only. No buy, no availability. */}
      <View style={[styles.actions, { backgroundColor: c.sf, paddingBottom: Math.max(insets.bottom, 26) }]}>
        <Pressable onPress={save} style={[styles.actionMain, { backgroundColor: c.pr }]} accessibilityRole="button">
          <BookmarkSimpleIcon size={20} color={c.prt} />
          <T weight={700} color={c.prt}>
            {saveNote ?? 'حفظ في قائمتي'}
          </T>
        </Pressable>
        <Pressable
          onPress={() => router.push({ pathname: '/search', params: { compareWith: d.register_number, focus: '1' } })}
          style={[styles.actionAlt, { borderColor: c.pr }]}
          accessibilityRole="button"
        >
          <ColumnsIcon size={20} color={c.pr} />
          <T weight={600} color={c.pr}>
            قارن
          </T>
        </Pressable>
        <Pressable onPress={share} style={[styles.actionIcon, { borderColor: c.pr }]} accessibilityLabel="مشاركة">
          <ShareNetworkIcon size={20} color={c.pr} />
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

function SameRow({ row, onShortage }: { row: SameIngredient; onShortage: boolean }) {
  const { c } = useTheme();
  const strength = row.ingredients
    .map((i) => (i.strength ? `${i.strength} ${unitAr(i.unit)}` : null))
    .filter(Boolean)
    .join(' + ');
  const meta = [strength, row.dosage_form_ar ?? row.dosage_form_en, row.marketing_company].filter(Boolean).join(' · ');
  const tier =
    row.verdict === 'equivalent'
      ? { label: 'نفس المادة الفعالة والتركيز والشكل', tone: 'neutral' as const, icon: <EqualsIcon size={14} color={c.pr} weight="fill" /> }
      : row.verdict === 'possible_needs_pharmacist_check'
        ? { label: 'محتمل ويحتاج مراجعة الصيدلي', tone: 'wn' as const, icon: <WarningIcon size={14} color={c.wn} weight="fill" /> }
        : { label: 'نفس المادة الفعالة، تركيز أو شكل مختلف', tone: 'muted' as const, icon: null };
  return (
    <Pressable onPress={() => router.push({ pathname: '/drug/[register]', params: { register: row.register_number } })}>
      <Card style={{ gap: 8 }}>
        <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <View style={{ flex: 1 }}>
            <T weight={700}>{displayName(row)}</T>
            {row.trade_name_en ? (
              <T size={13} color={c.ink2} latin align="right">
                {row.trade_name_en}
              </T>
            ) : null}
          </View>
          {row.price ? (
            <View style={{ alignItems: 'flex-start' }}>
              <T size={18} weight={700} latin>
                {row.price.amount}
              </T>
              <T size={11.5} color={c.ink2}>
                {row.price.currency_code === 'SAR' ? 'ريال (افتراضي)' : 'العملة غير مذكورة'}
              </T>
            </View>
          ) : null}
        </Row>
        <T size={13} color={c.ink2}>
          {meta}
        </T>
        <Pill label={tier.label} tone={tier.tone} radiusSize={radius.md} icon={tier.icon} />
        {onShortage ? <Pill tone="wn" label="مدرج أيضًا في قائمة النواقص" radiusSize={radius.md} /> : null}
      </Card>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { paddingTop: 20, paddingHorizontal: 16, gap: 28 },
  placeholder: {
    height: 180,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderStyle: 'dashed',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  banner: { borderWidth: 1.5, borderRadius: radius.lg, padding: 14, gap: 6 },
  ingredient: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', rowGap: 16 },
  fact: { width: '50%', paddingLeft: 12, gap: 2 },
  segment: { flexDirection: 'row-reverse', borderRadius: radius.md, padding: 3 },
  segmentItem: { flex: 1, minHeight: 38, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  link: { minHeight: 44, flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  actions: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row-reverse',
    gap: 8,
    paddingTop: 12,
    paddingHorizontal: 16,
    ...cardShadow,
  },
  actionMain: { flex: 2, minHeight: 48, borderRadius: radius.md, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  actionAlt: { flex: 1, minHeight: 48, borderRadius: radius.md, borderWidth: 1.5, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  actionIcon: { width: 48, minHeight: 48, borderRadius: radius.md, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
});
