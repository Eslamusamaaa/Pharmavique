// My list: alerts about my saved medicines, the medicines, and the allergies I recorded.
// Allergy flags match by active ingredient name only; they are a prompt to ask the pharmacist,
// never a clearance and never an instruction to stop or switch.
import { router } from 'expo-router';
import { ArrowRightIcon, BellIcon, TrashIcon, WarningIcon } from 'phosphor-react-native';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { displayName } from '@/api/client';
import {
  addAllergy,
  arabicMeError,
  getAlerts,
  getAllergies,
  getCurrentInteractions,
  getDigest,
  getSaved,
  markAlertsRead,
  removeAllergy,
  removeMedicine,
  searchIngredients,
  setMedicineStatus,
  type AlertItem,
  type Alerts,
  type CurrentInteractions,
  type Digest,
  type SavedMedicines,
} from '@/api/me';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { radius, useTheme } from '@/theme';

const KIND_AR: Record<AlertItem['kind'], string> = {
  price_changed: 'تغيّر السعر',
  withdrawn: 'اتسحب من السجل',
  relisted: 'رجع للسجل',
};

function alertLine(a: AlertItem): string {
  if (a.kind === 'price_changed') {
    const { old_price: from, new_price: to } = a.details;
    if (from && to) return `من ${from} إلى ${to}`;
  }
  return KIND_AR[a.kind];
}

export default function MyList() {
  const { c } = useTheme();
  const { account } = useAccount();
  const [saved, setSaved] = useState<SavedMedicines | null>(null);
  const [allergies, setAllergies] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alerts | null>(null);
  const [digest, setDigest] = useState<Digest | null>(null);
  const [among, setAmong] = useState<CurrentInteractions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [typed, setTyped] = useState('');
  const [options, setOptions] = useState<string[]>([]);

  const load = useCallback(async () => {
    try {
      const [s, a, al, d, ci] = await Promise.all([
        getSaved(),
        getAllergies(),
        getAlerts(),
        getDigest(7),
        getCurrentInteractions().catch(() => null),
      ]);
      setAmong(ci);
      setSaved(s);
      setAllergies(a.items.map((i) => i.ingredient));
      setAlerts(al);
      setDigest(d);
      setError(null);
    } catch (e) {
      setError(arabicMeError(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (account) load();
    else if (account === null) setLoading(false);
  }, [account, load]);

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

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
      await load();
    } catch (e) {
      setError(arabicMeError(e));
    }
  };

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
        قائمتي وتنبيهاتي
      </T>
    </View>
  );

  if (account === null) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <DisclaimerBar />
        <Message
          title="سجّل الدخول عشان تحفظ أدويتك"
          detail="القايمة والتنبيهات والحساسية محفوظة في حسابك، ومفيش حد غيرك بيشوفها."
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

  if (loading) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Loading />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}

        {digest ? (
          <Card style={{ gap: 4 }}>
            <T size={13} color={c.ink2}>
              ملخص الأسبوع
            </T>
            <T weight={600}>{digest.summary}</T>
          </Card>
        ) : null}

        <View style={{ gap: 10 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <H2>التنبيهات {alerts && alerts.unread ? `(${alerts.unread})` : ''}</H2>
            {alerts && alerts.unread ? (
              <Pressable onPress={() => run(() => markAlertsRead())}>
                <T size={13} weight={600} color={c.pr}>
                  اعتبرها كلها مقروءة
                </T>
              </Pressable>
            ) : null}
          </Row>
          {alerts && alerts.items.length > 0 ? (
            alerts.items.map((a) => (
              <Pressable
                key={a.id}
                onPress={() => {
                  if (!a.read) markAlertsRead(a.id).catch(() => undefined);
                  router.push({ pathname: '/drug/[register]', params: { register: a.register_number } });
                }}
              >
                <Card style={{ gap: 4, opacity: a.read ? 0.6 : 1 }}>
                  <Row gap={8}>
                    <BellIcon size={18} color={c.pr} weight={a.read ? 'regular' : 'fill'} />
                    <T weight={700} style={{ flex: 1 }}>
                      {a.product ? displayName(a.product) : a.register_number}
                    </T>
                  </Row>
                  <T size={14}>
                    {KIND_AR[a.kind]} · {alertLine(a)}
                  </T>
                  <T size={12} color={c.ink2}>
                    {new Date(a.occurred_at).toLocaleDateString('ar-EG')}
                  </T>
                </Card>
              </Pressable>
            ))
          ) : (
            <T size={14} color={c.ink2}>
              مفيش تنبيهات. هتظهر هنا لو سعر دواء محفوظ اتغيّر أو اتسحب من السجل.
            </T>
          )}
        </View>

        {among && among.findings.length > 0 ? (
          <Card style={{ gap: 6, borderWidth: 1.5, borderColor: c.wn }}>
            <Row gap={8}>
              <WarningIcon size={20} color={c.wn} weight="fill" />
              <T weight={700} style={{ flex: 1 }}>
                تداخلات مسجّلة بين أدويتك الحالية
              </T>
            </Row>
            {among.findings.map((x) => (
              <T key={`${x.about_register_number}-${x.with_register_number}-${x.ingredients.join('+')}`} size={13.5}>
                {x.ingredients.join(' ↔ ')}
                {x.severity ? ` · تصنيف المصدر: ${x.severity}` : ''}
              </T>
            ))}
            <T size={12.5} color={c.ink2}>
              {among.note}
            </T>
          </Card>
        ) : null}

        <View style={{ gap: 10 }}>
          <H2>أدويتي المحفوظة</H2>
          {saved && saved.items.length > 0 ? (
            [...saved.items]
              .sort((a, b) => Number(a.status === 'past') - Number(b.status === 'past'))
              .map((m) => (
              <Card key={m.register_number} style={{ gap: 6, opacity: m.status === 'past' ? 0.7 : 1 }}>
                <Row style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Pressable
                    style={{ flex: 1 }}
                    onPress={() => router.push({ pathname: '/drug/[register]', params: { register: m.register_number } })}
                  >
                    <T weight={700}>{m.product ? displayName(m.product) : m.register_number}</T>
                    {m.product?.trade_name_en ? (
                      <T size={13} color={c.ink2} latin align="right">
                        {m.product.trade_name_en}
                      </T>
                    ) : null}
                  </Pressable>
                  <Pressable onPress={() => run(() => removeMedicine(m.register_number))} accessibilityLabel="شيل من القايمة" style={styles.iconBtn}>
                    <TrashIcon size={20} color={c.ink2} />
                  </Pressable>
                </Row>
                {m.status === 'past' ? <Pill tone="muted" label="كنت باخده قبل كده" /> : null}
                <Pressable
                  onPress={() => run(() => setMedicineStatus(m.register_number, m.status === 'past' ? 'current' : 'past'))}
                  accessibilityRole="button"
                  style={{ minHeight: 40, justifyContent: 'center' }}
                >
                  <T size={13} weight={600} color={c.pr}>
                    {m.status === 'past' ? 'باخده دلوقتي' : 'مش باخده دلوقتي (كنت باخده قبل كده)'}
                  </T>
                </Pressable>
                {m.allergy_matches.map((x) => (
                  <Pill
                    key={`${x.allergy}-${x.ingredient}`}
                    tone="wn"
                    label={`فيه ${x.ingredient}، وإنت مسجّل حساسية من ${x.allergy}. اسأل الصيدلي`}
                    icon={<WarningIcon size={14} color={c.wn} weight="fill" />}
                  />
                ))}
              </Card>
            ))
          ) : (
            <T size={14} color={c.ink2}>
              لسه مفيش أدوية محفوظة. افتح أي دواء واضغط "حفظ في قائمتي".
            </T>
          )}
        </View>

        <View style={{ gap: 10 }}>
          <H2>الحساسية</H2>
          <Row gap={8} style={{ flexWrap: 'wrap' }}>
            {allergies.map((a) => (
              <Pressable key={a} onPress={() => run(() => removeAllergy(a))} accessibilityLabel={`شيل ${a}`}>
                <Pill tone="wn" label={`${a}  ✕`} />
              </Pressable>
            ))}
          </Row>
          <TextInput
            value={typed}
            onChangeText={setTyped}
            placeholder="اكتب أول حروف المادة الفعالة (بالإنجليزي)"
            placeholderTextColor={c.ink2}
            autoCapitalize="characters"
            autoCorrect={false}
            style={[styles.input, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }]}
          />
          {options.map((name) => (
            <Pressable
              key={name}
              onPress={() => {
                setTyped('');
                setOptions([]);
                run(() => addAllergy(name));
              }}
              style={[styles.option, { borderColor: c.ink2 }]}
            >
              <T latin align="left">
                {name}
              </T>
            </Pressable>
          ))}
          <T size={12.5} color={c.ink2}>
            {saved?.allergy_note ??
              'المطابقة باسم المادة الفعالة بس. حساسية الفصيلة (زي البنسلين) مش مغطاة، وعدم وجود تحذير مش معناه إن الدواء آمن.'}
          </T>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 24, paddingBottom: 80 },
  main: { minHeight: 48, paddingHorizontal: 24, borderRadius: radius.md, justifyContent: 'center' },
  input: { minHeight: 48, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 15, textAlign: 'left' },
  option: { minHeight: 44, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, justifyContent: 'center' },
});
