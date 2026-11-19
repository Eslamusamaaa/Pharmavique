// B6 · Box scan camera, B7 · confirm what was read, C1/C2 · prescription capture and review.
// The photo is sent once, read in memory and dropped by the server; nothing is looked up in the
// registry until the person confirms what was read.
import { CameraView, useCameraPermissions } from 'expo-camera';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { router, useFocusEffect } from 'expo-router';
import {
  ArrowRightIcon,
  CameraIcon,
  CheckIcon,
  ImageIcon,
  MagnifyingGlassIcon,
  PencilSimpleIcon,
  QuestionIcon,
  ShieldCheckIcon,
} from 'phosphor-react-native';
import { useCallback, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { displayName, friendlyError, scanImage, type ScanLine, type ScanResult } from '@/api/client';
import { DisclaimerBar, Pill, Row, T } from '@/components/ui';
import { cardShadow, fonts, radius, useTheme } from '@/theme';

type Kind = 'box' | 'prescription';
type Stage =
  | { kind: 'camera' }
  | { kind: 'reading'; photo: string }
  | { kind: 'review'; photo: string; result: ScanResult }
  | { kind: 'error'; photo: string | null; detail: string };

export default function Scan() {
  const { c } = useTheme();
  const [permission, requestPermission] = useCameraPermissions();
  const camera = useRef<CameraView>(null);
  const [kind, setKind] = useState<Kind>('box');
  const [stage, setStage] = useState<Stage>({ kind: 'camera' });
  const [focused, setFocused] = useState(true);

  // The camera runs only while this tab is on screen.
  useFocusEffect(
    useCallback(() => {
      setFocused(true);
      return () => setFocused(false);
    }, []),
  );

  const read = async (uri: string, mimeType: string) => {
    setStage({ kind: 'reading', photo: uri });
    try {
      const result = await scanImage(uri, mimeType, kind);
      setStage({ kind: 'review', photo: uri, result });
    } catch (e) {
      setStage({ kind: 'error', photo: uri, detail: friendlyError(e) });
    }
  };

  const shoot = async () => {
    const picture = await camera.current?.takePictureAsync({ quality: 0.7 });
    if (picture?.uri) read(picture.uri, 'image/jpeg');
  };

  const pick = async () => {
    const picked = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 });
    const asset = picked.assets?.[0];
    if (!picked.canceled && asset) read(asset.uri, asset.mimeType ?? 'image/jpeg');
  };

  const reset = () => setStage({ kind: 'camera' });

  if (stage.kind === 'review')
    return stage.result.kind === 'prescription' ? (
      <PrescriptionReview photo={stage.photo} result={stage.result} onBack={reset} />
    ) : (
      <BoxReview photo={stage.photo} result={stage.result} onBack={reset} />
    );

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: '#0B1A1C' }}>
      <View style={styles.cameraArea}>
        {stage.kind === 'camera' && permission?.granted && focused ? (
          <CameraView ref={camera} style={StyleSheet.absoluteFill} facing="back" />
        ) : stage.kind !== 'camera' && stage.photo ? (
          <Image source={{ uri: stage.photo }} style={StyleSheet.absoluteFill} contentFit="cover" />
        ) : null}

        {stage.kind === 'camera' && !permission?.granted ? (
          <View style={styles.center}>
            <CameraIcon size={56} color="#FFFFFF" />
            <T color="#FFFFFF" align="center">
              محتاجين إذن الكاميرا عشان نقرا اسم الدواء
            </T>
            <Pressable onPress={requestPermission} style={[styles.permission, { backgroundColor: c.pr }]}>
              <T weight={700} color={c.prt}>
                اسمح بالكاميرا
              </T>
            </Pressable>
          </View>
        ) : null}

        {stage.kind === 'camera' && permission?.granted ? (
          <View pointerEvents="none" style={styles.guideWrap}>
            <View style={[styles.guide, kind === 'prescription' && styles.guidePage]} />
            <View style={styles.hint}>
              <T size={14} color="#FFFFFF" align="center">
                {kind === 'box' ? 'وجّه الكاميرا للاسم والتركيز' : 'ضع الوصفة داخل الإطار وتأكد من وضوح الأسماء'}
              </T>
            </View>
          </View>
        ) : null}

        {stage.kind === 'reading' ? (
          <View style={[styles.center, styles.overlay]}>
            <ActivityIndicator size="large" color="#FFFFFF" />
            <T color="#FFFFFF" weight={600}>
              بنقرا الصورة…
            </T>
          </View>
        ) : null}

        {stage.kind === 'error' ? (
          <View style={[styles.center, styles.overlay]}>
            <T color="#FFFFFF" weight={700} align="center">
              مقدرناش نقرا الصورة
            </T>
            <T size={14} color="#FFFFFF" align="center">
              {stage.detail}
            </T>
            <Pressable onPress={reset} style={[styles.permission, { backgroundColor: c.pr }]}>
              <T weight={700} color={c.prt}>
                جرّب تاني
              </T>
            </Pressable>
          </View>
        ) : null}
      </View>

      <View style={styles.controls}>
        <View style={styles.toggle}>
          {(['box', 'prescription'] as const).map((k) => (
            <Pressable key={k} onPress={() => setKind(k)} style={[styles.toggleItem, kind === k && { backgroundColor: '#FFFFFF' }]}>
              <T size={14} weight={kind === k ? 700 : 400} color={kind === k ? c.pr : '#FFFFFF'} align="center">
                {k === 'box' ? 'علبة' : 'وصفة'}
              </T>
            </Pressable>
          ))}
        </View>
        <Row style={{ justifyContent: 'space-between', alignSelf: 'stretch', paddingHorizontal: 32 }}>
          <View style={{ width: 52 }} />
          <Pressable
            onPress={shoot}
            disabled={stage.kind !== 'camera' || !permission?.granted}
            style={styles.shutter}
            accessibilityLabel="صوّر"
          >
            <View style={styles.shutterInner} />
          </Pressable>
          <Pressable onPress={pick} disabled={stage.kind === 'reading'} style={styles.gallery} accessibilityLabel="اختار صورة من المعرض">
            <ImageIcon size={26} color="#FFFFFF" />
          </Pressable>
        </Row>
        <Row gap={6}>
          <ShieldCheckIcon size={16} color="#9FB7B8" />
          <T size={13} color="#9FB7B8">
            لا نحتفظ بصورتك بعد المعالجة
          </T>
        </Row>
      </View>
    </SafeAreaView>
  );
}

function ReviewHeader({ title, onBack }: { title: string; onBack: () => void }) {
  const { c } = useTheme();
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} style={styles.iconBtn} accessibilityLabel="رجوع">
        <ArrowRightIcon size={24} color={c.ink} />
      </Pressable>
      <T size={17} weight={700} style={{ flex: 1 }}>
        {title}
      </T>
    </View>
  );
}

function Candidates({ line }: { line: ScanLine }) {
  const { c } = useTheme();
  if (!line.candidates.length)
    return (
      <T size={13} color={c.ink2}>
        ملقيناش اسم قريب في السجل الرسمي. عدّل الاسم وابحث.
      </T>
    );
  return (
    <View style={{ gap: 6 }}>
      <T size={12.5} color={c.ink2}>
        الأقرب في السجل الرسمي
      </T>
      {line.candidates.map((cand) => (
        <Pressable
          key={cand.register_number}
          onPress={() => router.push({ pathname: '/drug/[register]', params: { register: cand.register_number } })}
          style={[styles.candidate, { borderColor: c.ln }]}
        >
          <View style={{ flex: 1 }}>
            <T weight={600}>{displayName(cand)}</T>
            {cand.trade_name_en ? (
              <T size={12.5} color={c.ink2} latin align="right">
                {cand.trade_name_en}
              </T>
            ) : null}
          </View>
          <ArrowRightIcon size={18} color={c.ink2} style={{ transform: [{ scaleX: -1 }] }} />
        </Pressable>
      ))}
    </View>
  );
}

// B7 · confirm what was read (box)
function BoxReview({ photo, result, onBack }: { photo: string; result: ScanResult; onBack: () => void }) {
  const { c } = useTheme();
  const first = result.lines[0];
  const [name, setName] = useState(first ? [first.name, first.strength].filter(Boolean).join(' ') : '');

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <ReviewHeader title="راجع ما قرأناه" onBack={onBack} />
      <ScrollView contentContainerStyle={styles.review}>
        <Image source={{ uri: photo }} style={styles.photo} contentFit="cover" />
        <T size={14} color={c.ink2}>
          لن نبحث قبل أن تؤكد. عدّل أي حقل غير صحيح.
        </T>
        {result.status === 'nothing_read' ? (
          <View style={[styles.card, { backgroundColor: c.sf }, cardShadow]}>
            <T weight={700}>مقدرناش نقرا اسم دواء في الصورة</T>
            <T size={14} color={c.ink2}>
              جرّب صورة أوضح للاسم والتركيز، أو اكتب الاسم هنا.
            </T>
          </View>
        ) : null}
        <View style={[styles.card, { backgroundColor: c.sf }, cardShadow]}>
          <T size={12.5} color={c.ink2}>
            اسم الدواء والتركيز
          </T>
          <Row gap={8}>
            <TextInput
              value={name}
              onChangeText={setName}
              placeholder="اكتب الاسم"
              placeholderTextColor={c.ink2}
              style={[styles.field, { color: c.ink, fontFamily: fonts.ar[600] }]}
            />
            <PencilSimpleIcon size={18} color={c.ink2} />
          </Row>
          {first?.form ? (
            <T size={13} color={c.ink2}>
              {`الشكل المقروء: ${first.form}`}
            </T>
          ) : null}
          {first ? <Candidates line={first} /> : null}
        </View>
        <Pressable
          onPress={() => name.trim() && router.push({ pathname: '/search', params: { q: name.trim() } })}
          disabled={!name.trim()}
          style={[styles.primary, { backgroundColor: c.pr, opacity: name.trim() ? 1 : 0.5 }]}
        >
          <MagnifyingGlassIcon size={20} color={c.prt} />
          <T weight={700} color={c.prt}>
            ابحث
          </T>
        </Pressable>
        <Row gap={6} style={{ justifyContent: 'center' }}>
          <ShieldCheckIcon size={16} color={c.ink2} />
          <T size={13} color={c.ink2}>
            لا نحتفظ بصورتك بعد المعالجة
          </T>
        </Row>
      </ScrollView>
    </SafeAreaView>
  );
}

// C2 · prescription review: each line confirmed by a person; the dose is never read
function PrescriptionReview({ photo, result, onBack }: { photo: string; result: ScanResult; onBack: () => void }) {
  const { c } = useTheme();
  const [names, setNames] = useState(result.lines.map((l) => l.name));
  const [confirmed, setConfirmed] = useState<boolean[]>(result.lines.map(() => false));
  const count = confirmed.filter(Boolean).length;

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <ReviewHeader title="راجع أسماء الأدوية" onBack={onBack} />
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.review}>
        <Image source={{ uri: photo }} style={styles.photoSmall} contentFit="cover" />
        <T size={14} color={c.ink2}>
          {result.lines.length
            ? `${result.lines.length} أسماء مقروءة. أكّد كل صف قبل البحث.`
            : 'مقدرناش نقرا أسماء أدوية في الوصفة. جرّب صورة أوضح.'}
        </T>
        {result.lines.map((line, i) => (
          <View
            key={`${line.raw_text}-${i}`}
            style={[
              styles.card,
              { backgroundColor: c.sf, borderWidth: 1.5, borderColor: confirmed[i] ? c.ok : c.wn },
              cardShadow,
            ]}
          >
            <Row style={{ justifyContent: 'space-between' }}>
              <T size={13} color={c.ink2}>{`سطر ${i + 1}`}</T>
              {confirmed[i] ? <Pill tone="ok" label="مؤكَّد" /> : <Pill tone="wn" label="محتاج مراجعة" />}
            </Row>
            <Row gap={8}>
              <TextInput
                value={names[i]}
                onChangeText={(v) => setNames((all) => all.map((n, j) => (j === i ? v : n)))}
                style={[styles.field, { color: c.ink, fontFamily: fonts.ar[600] }]}
              />
              <PencilSimpleIcon size={18} color={c.ink2} />
            </Row>
            <T size={13} color={c.ink2}>
              {`التركيز والشكل المقروء: ${[line.strength, line.form].filter(Boolean).join(' · ') || 'غير مقروء'}`}
            </T>
            <Row gap={6}>
              <QuestionIcon size={16} color={c.wn} weight="fill" />
              <T size={13} color={c.wn} weight={600}>
                {`تعليمات الجرعة: ${line.dose ?? 'غير واضح'}`}
              </T>
            </Row>
            <Candidates line={line} />
            <Pressable
              onPress={() => setConfirmed((all) => all.map((v, j) => (j === i ? !v : v)))}
              style={[styles.confirm, { borderColor: c.ok, backgroundColor: confirmed[i] ? c.oks : 'transparent' }]}
            >
              <CheckIcon size={18} color={c.ok} weight="bold" />
              <T weight={600} color={c.ok}>
                {confirmed[i] ? 'تم التأكيد' : 'تأكيد السطر'}
              </T>
            </Pressable>
          </View>
        ))}
        {result.lines.length ? (
          <>
            <Pressable
              onPress={() => {
                const first = names.find((_, i) => confirmed[i]);
                if (first) router.push({ pathname: '/search', params: { q: first } });
              }}
              disabled={!count}
              style={[styles.primary, { backgroundColor: c.pr, opacity: count ? 1 : 0.5 }]}
            >
              <MagnifyingGlassIcon size={20} color={c.prt} />
              <T weight={700} color={c.prt}>{`عرض نتائج المؤكَّد (${count})`}</T>
            </Pressable>
            <T size={13} color={c.ink2} align="center">
              الصف غير المؤكَّد لن يُبحث عنه
            </T>
          </>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  cameraArea: { flex: 1, overflow: 'hidden' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 14, padding: 24 },
  overlay: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(0,0,0,0.55)' },
  permission: { paddingVertical: 12, paddingHorizontal: 22, borderRadius: radius.md },
  guideWrap: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, alignItems: 'center', justifyContent: 'center', gap: 16 },
  guide: { width: '78%', aspectRatio: 1.6, borderWidth: 2.5, borderColor: '#FFFFFF', borderRadius: radius.lg },
  guidePage: { width: '72%', aspectRatio: 0.72 },
  hint: { backgroundColor: 'rgba(0,0,0,0.55)', borderRadius: radius.pill, paddingVertical: 6, paddingHorizontal: 14 },
  controls: { alignItems: 'center', gap: 14, paddingTop: 14, paddingBottom: 18 },
  toggle: { flexDirection: 'row-reverse', backgroundColor: 'rgba(255,255,255,0.15)', borderRadius: radius.pill, padding: 3 },
  toggleItem: { minWidth: 88, paddingVertical: 8, borderRadius: radius.pill },
  shutter: { width: 76, height: 76, borderRadius: 38, borderWidth: 4, borderColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  shutterInner: { width: 58, height: 58, borderRadius: 29, backgroundColor: '#FFFFFF' },
  gallery: { width: 52, height: 52, borderRadius: radius.md, backgroundColor: 'rgba(255,255,255,0.15)', alignItems: 'center', justifyContent: 'center' },
  header: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  review: { padding: 16, gap: 14 },
  photo: { height: 200, borderRadius: radius.lg },
  photoSmall: { height: 140, borderRadius: radius.lg },
  card: { borderRadius: radius.lg, padding: 16, gap: 10 },
  field: { flex: 1, minWidth: 0, fontSize: 18, textAlign: 'right', writingDirection: 'rtl', paddingVertical: 4 },
  candidate: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, borderWidth: 1, borderRadius: radius.md, padding: 10 },
  confirm: { minHeight: 44, borderWidth: 1.5, borderRadius: radius.md, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  primary: { minHeight: 52, borderRadius: radius.md, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
});
