// Shelf scan (pharmacists): a photo of a shelf proposes the boxes it could read, with how sure the
// match is. Nothing is added until the pharmacist ticks a box and confirms. The list holds which
// medicines are shelved, never counts or stock.
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { ArrowRightIcon, CameraIcon, CheckSquareIcon, ImageIcon, SquareIcon, TrashIcon } from 'phosphor-react-native';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { displayName, friendlyError, type ScanLine, type ScanResult } from '@/api/client';
import {
  arabicMeError,
  confirmShelf,
  getFeatures,
  getShelf,
  removeFromShelf,
  scanShelfPhoto,
  type Shelf,
} from '@/api/me';
import { Card, DisclaimerBar, H2, Loading, Message, Pill, PrimaryButton, Row, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { radius, useTheme } from '@/theme';

type Stage = { kind: 'start' } | { kind: 'reading' } | { kind: 'review'; result: ScanResult } | { kind: 'error'; detail: string };

// The API's note is in English; the app speaks Saudi Arabic.
const SHELF_NOTE = 'الأدوية اللي أكّدتها بعد مسح الرف. ما فيها كميات وما تقول شي عن المخزون.';

export default function ShelfScan() {
  const { c } = useTheme();
  const { account } = useAccount();
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [stage, setStage] = useState<Stage>({ kind: 'start' });
  const [chosen, setChosen] = useState<Record<number, string | null>>({}); // line index -> register number
  const [shelf, setShelf] = useState<Shelf | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadShelf = useCallback(async () => {
    try {
      setShelf(await getShelf());
    } catch {
      setShelf(null);
    }
  }, []);

  useEffect(() => {
    getFeatures().then((f) => setEnabled(f.shelf_scan));
  }, []);
  useEffect(() => {
    if (account) loadShelf();
  }, [account, loadShelf]);

  const read = async (uri: string, mimeType: string) => {
    setMessage(null);
    setStage({ kind: 'reading' });
    try {
      const result = await scanShelfPhoto(uri, mimeType);
      setChosen({});
      setStage({ kind: 'review', result });
    } catch (e) {
      setStage({ kind: 'error', detail: friendlyError(e) });
    }
  };

  const shoot = async () => {
    const picture = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7 });
    const asset = picture.assets?.[0];
    if (!picture.canceled && asset) read(asset.uri, asset.mimeType ?? 'image/jpeg');
  };
  const pick = async () => {
    const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 });
    const asset = picked.assets?.[0];
    if (!picked.canceled && asset) read(asset.uri, asset.mimeType ?? 'image/jpeg');
  };

  const confirm = async () => {
    const registers = Object.values(chosen).filter((r): r is string => Boolean(r));
    if (registers.length === 0) return;
    try {
      const out = await confirmShelf(registers);
      setMessage(`انضاف ${out.added} دواء لرف الصيدلية${out.already_on_the_shelf ? ` (${out.already_on_the_shelf} كانوا موجودين)` : ''}.`);
      setStage({ kind: 'start' });
      await loadShelf();
    } catch (e) {
      setMessage(arabicMeError(e));
    }
  };

  const header = (
    <View style={styles.topBar}>
      <Pressable
        onPress={() => (stage.kind !== 'start' ? setStage({ kind: 'start' }) : router.canGoBack() ? router.back() : router.replace('/account'))}
        style={styles.iconBtn}
        accessibilityLabel="رجوع"
      >
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        مسح الرف
      </T>
    </View>
  );

  if (account === null || enabled === false || enabled === null) {
    return (
      <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
        {header}
        {enabled === null && account !== null ? (
          <Loading />
        ) : (
          <Message
            title={account === null ? 'هذي الشاشة لحسابات الصيادلة' : 'مسح الرف غير مفعّل على هذا السيرفر'}
            detail={
              account === null
                ? 'سجّل الدخول بحساب صيدلي.'
                : 'هذي الميزة مقفلة على هذا السيرفر. المسؤول عن السيرفر هو من يفعّلها.'
            }
          />
        )}
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      {header}
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content}>
        {message ? (
          <T size={14} color={c.ok}>
            {message}
          </T>
        ) : null}

        {stage.kind === 'start' ? (
          <>
            <PrimaryButton label="صوّر الرف" icon={<CameraIcon size={20} color={c.prt} />} onPress={shoot} />
            <PrimaryButton label="اختر صورة" icon={<ImageIcon size={20} color={c.pr} />} onPress={pick} outline />
            <T size={13} color={c.ink2}>
              الصورة تُقرأ وتُمسح ولا تُحفظ. الأسماء المقترحة تحتاج مراجعتك: ما فيه دواء يُضاف بدون ما تأكّده.
            </T>
          </>
        ) : null}

        {stage.kind === 'reading' ? <Loading /> : null}

        {stage.kind === 'error' ? (
          <T size={14} color={c.rd} align="center">
            {stage.detail}
          </T>
        ) : null}

        {stage.kind === 'review' ? (
          <Review result={stage.result} chosen={chosen} setChosen={setChosen} onConfirm={confirm} />
        ) : null}

        {stage.kind === 'start' && shelf ? (
          <View style={{ gap: 8 }}>
            <H2>رف الصيدلية ({shelf.count})</H2>
            {shelf.items.map((i) => (
              <Row key={i.register_number} style={{ justifyContent: 'space-between' }}>
                <T size={14} latin style={{ flex: 1 }} align="left">
                  {i.product ? displayName(i.product) : i.register_number}
                </T>
                <Pressable
                  onPress={() => removeFromShelf(i.register_number).then(loadShelf)}
                  style={styles.iconBtn}
                  accessibilityLabel="احذف من الرف"
                >
                  <TrashIcon size={20} color={c.ink2} />
                </Pressable>
              </Row>
            ))}
            <T size={12.5} color={c.ink2}>
              {SHELF_NOTE}
            </T>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function Review({
  result,
  chosen,
  setChosen,
  onConfirm,
}: {
  result: ScanResult;
  chosen: Record<number, string | null>;
  setChosen: (value: Record<number, string | null>) => void;
  onConfirm: () => void;
}) {
  const { c } = useTheme();
  const picked = Object.values(chosen).filter(Boolean).length;
  if (result.lines.length === 0)
    return (
      <T size={14} color={c.ink2}>
        ما قدرت أقرأ أي اسم دواء في الصورة. جرّب صورة أقرب وأوضح.
      </T>
    );
  return (
    <View style={{ gap: 12 }}>
      <T size={13} color={c.ink2}>
        {result.lines.length} صندوق مقترح. اختر المطابقة الصحيحة لكل واحد، واترك اللي مو متأكد منه.
      </T>
      {result.lines.map((line: ScanLine, index: number) => (
        <Card key={`${line.raw_text}-${index}`} style={{ gap: 6 }}>
          <T weight={700} latin align="left">
            {line.raw_text}
          </T>
          {line.candidates.length === 0 ? (
            <Pill tone="muted" label="ما فيه مطابقة في السجل" />
          ) : (
            line.candidates.map((cand) => {
              const on = chosen[index] === cand.register_number;
              return (
                <Pressable
                  key={cand.register_number}
                  onPress={() => setChosen({ ...chosen, [index]: on ? null : cand.register_number })}
                  accessibilityRole="checkbox"
                  accessibilityState={{ checked: on }}
                  style={[styles.candidate, { borderColor: on ? c.pr : c.ln, backgroundColor: on ? c.prs : 'transparent' }]}
                >
                  {on ? <CheckSquareIcon size={22} color={c.pr} weight="fill" /> : <SquareIcon size={22} color={c.ink2} />}
                  <View style={{ flex: 1 }}>
                    <T size={14} latin align="left">
                      {cand.trade_name_en ?? cand.trade_name_ar ?? cand.register_number}
                    </T>
                    <T size={12} color={c.ink2}>
                      درجة التطابق {Math.round(cand.score * 100)}٪
                    </T>
                  </View>
                </Pressable>
              );
            })
          )}
        </Card>
      ))}
      <PrimaryButton label={`أكّد ${picked} وأضفهم للرف`} onPress={onConfirm} />
    </View>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14, paddingBottom: 80 },
  candidate: {
    minHeight: 52,
    borderWidth: 1.5,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 10,
  },
});
