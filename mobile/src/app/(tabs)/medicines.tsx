// أدويتي: add my medicines and allergies, see what changed for them, and the interactions among them.
// Allergy and interaction flags match by active ingredient name; they are a prompt to ask the
// pharmacist or doctor, never a clearance and never an instruction to stop or switch.
import { router } from 'expo-router';
import { WarningIcon } from 'phosphor-react-native';
import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  addAllergy,
  arabicMeError,
  getAlerts,
  getAllergies,
  getCurrentInteractions,
  getSaved,
  removeAllergy,
  removeMedicine,
  saveMedicine,
  setMedicineStatus,
  type Alerts,
  type CurrentInteractions,
  type SavedMedicines,
} from '@/api/me';
import { FormScroll } from '@/components/FormScroll';
import { AddMedicine } from '@/components/medicines/AddMedicine';
import { AlertsSection } from '@/components/medicines/AlertsSection';
import { Allergies } from '@/components/medicines/Allergies';
import { SavedCard } from '@/components/medicines/SavedCard';
import { Card, DisclaimerBar, H2, Loading, PrimaryButton, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { useTheme } from '@/theme';

export default function Medicines() {
  const { c } = useTheme();
  const { account } = useAccount();
  const [saved, setSaved] = useState<SavedMedicines | null>(null);
  const [allergies, setAllergies] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alerts | null>(null);
  const [among, setAmong] = useState<CurrentInteractions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [s, a, al, ci] = await Promise.all([
        getSaved(),
        getAllergies(),
        getAlerts(),
        getCurrentInteractions().catch(() => null),
      ]);
      setSaved(s);
      setAllergies(a.items.map((i) => i.ingredient));
      setAlerts(al);
      setAmong(ci);
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
      <T size={17} weight={700}>
        أدويتي
      </T>
    </View>
  );

  if (account === null) {
    return (
      <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <DisclaimerBar />
        <View style={styles.signedOut}>
          <T size={18} weight={700} align="center">
            سجّل دخولك عشان تحفظ أدويتك
          </T>
          <T size={14} color={c.ink2} align="center">
            تضيف أدويتك وحساسيتك، ويوصلك تنبيه إذا تغيّر سعر أحد أدويتك أو انسحب. وما أحد غيرك يشوفها.
          </T>
          <PrimaryButton label="تسجيل الدخول أو إنشاء حساب" onPress={() => router.push('/sign-in')} />
          <PrimaryButton label="افحص التداخل بدون حساب" outline onPress={() => router.push('/my-medicines')} />
        </View>
      </SafeAreaView>
    );
  }

  if (loading) {
    return (
      <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        <Loading />
      </SafeAreaView>
    );
  }

  const items = [...(saved?.items ?? [])].sort((a, b) => Number(a.status === 'past') - Number(b.status === 'past'));
  const current = items.filter((m) => m.status === 'current').length;

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <FormScroll contentStyle={styles.content}>
        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}

        <Card style={{ gap: 4 }}>
          <T size={13} color={c.ink2}>
            ملخص
          </T>
          <T weight={600}>
            {current} دواء أتناوله الحين · {allergies.length} حساسية · {alerts?.unread ?? 0} تنبيه جديد
          </T>
        </Card>

        <View style={{ gap: 10 }}>
          <H2>أضف دواء</H2>
          <AddMedicine
            saved={new Set(items.map((m) => m.register_number))}
            onAdd={(register) => run(() => saveMedicine(register))}
          />
        </View>

        <View style={{ gap: 10 }}>
          <H2>أدويتي ({items.length})</H2>
          {items.length > 0 ? (
            items.map((m) => (
              <SavedCard
                key={m.register_number}
                item={m}
                onToggle={() => run(() => setMedicineStatus(m.register_number, m.status === 'past' ? 'current' : 'past'))}
                onRemove={() => run(() => removeMedicine(m.register_number))}
              />
            ))
          ) : (
            <T size={14} color={c.ink2}>
              للحين ما أضفت أي دواء. ابحث عن دواء فوق وأضفه.
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

        <Allergies
          items={allergies}
          note={
            saved?.allergy_note ??
            'المطابقة باسم المادة الفعالة فقط. حساسية الفصيلة (مثل البنسلين) غير مغطاة، وعدم وجود تحذير لا يعني أن الدواء آمن.'
          }
          onAdd={(name) => run(() => addAllergy(name))}
          onRemove={(name) => run(() => removeAllergy(name))}
        />

        <AlertsSection alerts={alerts} onChanged={load} />
      </FormScroll>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, justifyContent: 'center', paddingHorizontal: 16 },
  content: { padding: 16, gap: 24 },
  signedOut: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
});
