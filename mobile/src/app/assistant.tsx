// B16 · Assistant: levels, cited answers, redirect, not found, listen (pharmavique-wireframes/PvB3).
import { router, useLocalSearchParams } from 'expo-router';
import {
  ArrowRightIcon,
  CameraIcon,
  FileTextIcon,
  GlobeIcon,
  FirstAidKitIcon,
  InfoIcon,
  LinkSimpleIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  PaperPlaneTiltIcon,
  SealCheckIcon,
  SpeakerHighIcon,
  StopIcon,
  WarningIcon,
  XIcon,
} from 'phosphor-react-native';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Linking,
  Keyboard,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  askAssistant,
  friendlyError,
  scanImage,
  type AssistantAnswer,
  type ConversationTurn,
} from '@/api/client';
import { askWithMyMedicines } from '@/api/me';
import { HistoryCard } from '@/components/history-card';
import { useAccount } from '@/state/auth';
import { DisclaimerBar, Row, T } from '@/components/ui';
import { roleInfo, useRole } from '@/state/role';
import { useSpeaker, useVoiceInput } from '@/state/voice';
import { cardShadow, fonts, radius, useTheme } from '@/theme';

type Turn =
  | { id: string; role: 'user'; text: string; sent?: string; photo?: string }
  | { id: string; role: 'assistant'; answer: AssistantAnswer }
  | { id: string; role: 'pending' }
  | { id: string; role: 'error'; text: string };

let counter = 0;
const nextId = () => `t${++counter}`;

export default function Assistant() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ register?: string; name?: string; q?: string }>();
  const { account } = useAccount();
  const [useMine, setUseMine] = useState(false);
  const { role } = useRole();
  const { level, suggestions } = roleInfo(role ?? 'patient');
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const mic = useVoiceInput();
  const speaker = useSpeaker();
  const busy = turns.some((t) => t.role === 'pending');
  const [reading, setReading] = useState(false);
  const [photo, setPhoto] = useState<{ uri: string; mimeType: string } | null>(null);
  const readingNow = useRef(false);

  const ask = async (question: string, spoken = false, shown?: string, photoUri?: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const pendingId = nextId();
    // The conversation so far, so follow-ups ("and the 40 mg one?") keep their meaning.
    const history: ConversationTurn[] = turns
      .flatMap((t): ConversationTurn[] =>
        t.role === 'user'
          ? [{ role: 'user', text: t.sent ?? t.text }]
          : t.role === 'assistant'
            ? [{ role: 'assistant', text: t.answer.answer }]
            : [],
      )
      .slice(-6);
    setText('');
    Keyboard.dismiss(); // the answer is what matters now, not the keyboard
    setTurns((all) => [...all, { id: nextId(), role: 'user', text: shown ?? q, sent: q, photo: photoUri }, { id: pendingId, role: 'pending' }]);
    try {
      const answer =
        useMine && account && params.register
          ? await askWithMyMedicines({ question: q, level, register_number: params.register, spoken, history })
          : await askAssistant({ question: q, level, register_number: params.register ?? null, spoken, history });
      setTurns((all) => all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'assistant', answer } : t)));
      // A question asked by voice is answered by voice too (Saudi Arabic).
      if (spoken && !answer.refused) speaker.speak(pendingId, answer.answer);
    } catch (e) {
      setTurns((all) => all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'error', text: friendlyError(e) } : t)));
    }
  };

  // A photo stays attached until the person adds the question to send with it. The box scan only
  // transcribes what is printed on the box; the name it read joins the question. No image goes to
  // the assistant's language model (ADR-017).
  const attach = (picked: ImagePicker.ImagePickerResult) => {
    const asset = picked.assets?.[0];
    if (picked.canceled || !asset) return;
    setPhoto({ uri: asset.uri, mimeType: asset.mimeType ?? 'image/jpeg' });
  };

  const sendWithPhoto = async () => {
    const attached = photo;
    const asked = text.trim();
    if (!attached || !asked || readingNow.current || busy) return;
    readingNow.current = true;
    setReading(true);
    Keyboard.dismiss();
    try {
      const result = await scanImage(attached.uri, attached.mimeType, 'box');
      const line = result.lines[0];
      setPhoto(null);
      if (!line) {
        setTurns((all) => [
          ...all,
          { id: nextId(), role: 'error', text: 'ما قدرت أقرأ اسم الدواء من الصورة. جرّب صورة أوضح للاسم والتركيز.' },
        ]);
        return;
      }
      const printed = [line.name, line.strength, line.form].filter(Boolean).join(' ').slice(0, 120);
      readingNow.current = false;
      setReading(false);
      await ask(`${asked}
مكتوب على العلبة (مقروء من صورة): "${printed}"`, false, asked, attached.uri);
    } catch (e) {
      // the photo stays attached so the person can send again
      setTurns((all) => [...all, { id: nextId(), role: 'error', text: friendlyError(e) }]);
    } finally {
      readingNow.current = false;
      setReading(false);
    }
  };

  const send = () => (photo ? sendWithPhoto() : ask(text));

  // On the website the browser's own file chooser already offers the camera or the library.
  const onPhoto = () =>
    Platform.OS === 'web'
      ? ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 }).then(attach)
      : Alert.alert('أضف صورة دواء', 'صوّر العلبة أو اختر صورة من المعرض', [
      {
        text: 'الكاميرا',
        onPress: async () => {
          const permission = await ImagePicker.requestCameraPermissionsAsync();
          if (!permission.granted) {
            setTurns((all) => [
              ...all,
              { id: nextId(), role: 'error', text: 'نحتاج إذن الكاميرا. فعّله من إعدادات الجوال.' },
            ]);
            return;
          }
          attach(await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], quality: 0.7 }));
        },
      },
      {
        text: 'المعرض',
        onPress: async () =>
          attach(await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], quality: 0.7 })),
      },
      { text: 'إلغاء', style: 'cancel' },
    ]);

  useEffect(() => {
    if (params.q) ask(params.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.q]);

  useEffect(() => {
    setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [turns]);

  const onMic = async () => {
    if (mic.state === 'listening') {
      const heard = await mic.stop();
      if (heard) ask(heard, true);
    } else if (mic.state === 'idle') {
      await mic.start();
    }
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))} style={styles.iconBtn} accessibilityLabel="رجوع">
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }} numberOfLines={1}>
          {params.name ? `اسأل عن ${params.name}` : 'اسأل عن بيانات الأدوية'}
        </T>
      </View>
      <DisclaimerBar />
      {account && params.register ? (
        <Pressable
          onPress={() => setUseMine((v) => !v)}
          style={[styles.mine, { backgroundColor: useMine ? c.prs : c.sf, borderColor: useMine ? c.pr : c.ln }]}
          accessibilityRole="switch"
          accessibilityState={{ checked: useMine }}
        >
          <T size={14} weight={600} style={{ flex: 1 }}>
            {useMine ? 'بقارن هذا الدواء بأدويتي الحالية' : 'قارن هذا الدواء بأدويتي الحالية'}
          </T>
          <T size={12.5} color={c.ink2}>
            {useMine ? 'شغّال' : 'مقفول'}
          </T>
        </Pressable>
      ) : null}

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView
          ref={scroll}
          contentContainerStyle={styles.thread}
          keyboardShouldPersistTaps="handled"
          keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
        >
          {turns.length === 0 ? (
            <View style={{ gap: 10, paddingTop: 8 }}>
              <T size={15} color={c.ink2}>
                اسأل عن أي دواء مسجل: المادة الفعالة، السعر المسجل، البدائل بنفس المادة، أو التحذيرات الرسمية.
              </T>
            </View>
          ) : null}
          {turns.map((turn) => {
            if (turn.role === 'user')
              return (
                <View key={turn.id} style={[styles.userBubble, { backgroundColor: c.pr }]}>
                  {turn.photo ? <Image source={{ uri: turn.photo }} style={styles.bubbleThumb} contentFit="cover" /> : null}
                  <T color={c.prt} weight={500}>
                    {turn.text}
                  </T>
                </View>
              );
            if (turn.role === 'pending')
              return (
                <Row key={turn.id} gap={8} style={[styles.pending, { backgroundColor: c.sf }]}>
                  <ActivityIndicator size="small" color={c.ink2} />
                  <T size={14} color={c.ink2}>
                    جارٍ البحث في بياناتنا…
                  </T>
                </Row>
              );
            if (turn.role === 'error')
              return (
                <View key={turn.id} style={[styles.card, { backgroundColor: c.sf, borderColor: c.ln, borderWidth: 1 }]}>
                  <T size={14} color={c.ink2}>
                    {turn.text}
                  </T>
                </View>
              );
            return (
              <View key={turn.id} style={{ gap: 10 }}>
                <AnswerCard
                  answer={turn.answer}
                  listening={speaker.loadingId === turn.id}
                  onListen={() => speaker.speak(turn.id, turn.answer.answer)}
                />
                {turn.answer.history_check ? <HistoryCard check={turn.answer.history_check} /> : null}
              </View>
            );
          })}
          {reading ? (
            <Row gap={8} style={[styles.pending, { backgroundColor: c.sf }]}>
              <ActivityIndicator size="small" color={c.ink2} />
              <T size={14} color={c.ink2}>
                جارٍ قراءة الصورة…
              </T>
            </Row>
          ) : null}
          {mic.error ? (
            <T size={13} color={c.rd}>
              {mic.error}
            </T>
          ) : null}
          {speaker.error ? (
            <T size={13} color={c.rd}>
              {speaker.error}
            </T>
          ) : null}
          {turns.length === 0 ? (
            <View style={styles.suggestions}>
              {suggestions.map((s) => (
                <Pressable key={s} onPress={() => ask(s)} style={[styles.chip, { backgroundColor: c.sf, borderColor: c.ln }]}>
                  <T size={14}>{s}</T>
                </Pressable>
              ))}
            </View>
          ) : null}
        </ScrollView>

        {photo ? (
          <View style={[styles.attached, { backgroundColor: c.sf, borderColor: c.ln }]}>
            <Image source={{ uri: photo.uri }} style={styles.thumb} contentFit="cover" />
            <T size={13} color={c.ink2} style={{ flex: 1 }}>
              صورة مرفقة. اكتب سؤالك عنها ثم أرسل.
            </T>
            <Pressable onPress={() => setPhoto(null)} accessibilityLabel="أزل الصورة" style={styles.iconBtn}>
              <XIcon size={20} color={c.ink2} />
            </Pressable>
          </View>
        ) : null}

        <View style={[styles.inputBar, { backgroundColor: c.bg, paddingBottom: Math.max(insets.bottom, 12) }]}>
          <TextInput
            value={text}
            onChangeText={setText}
            onSubmitEditing={send}
            placeholder={
              mic.state === 'listening'
                ? 'نسمعك… اضغط مرة ثانية إذا خلصت'
                : photo
                  ? 'اكتب سؤالك عن الصورة'
                  : 'اكتب أو تكلّم عن اسم أو مادة أو سعر'
            }
            placeholderTextColor={c.ink2}
            multiline
            style={[styles.input, { backgroundColor: c.sf, color: c.ink, fontFamily: fonts.ar[400] }, cardShadow]}
          />
          <Pressable
            onPress={onPhoto}
            disabled={busy || reading}
            style={[styles.roundBtn, { backgroundColor: c.prs, opacity: busy || reading ? 0.5 : 1 }]}
            accessibilityLabel="أضف صورة دواء"
          >
            <CameraIcon size={22} color={c.pr} />
          </Pressable>
          <Pressable
            onPress={onMic}
            style={[styles.roundBtn, { backgroundColor: mic.state === 'listening' ? c.rd : c.prs }]}
            accessibilityLabel={mic.state === 'listening' ? 'إيقاف التسجيل' : 'اسأل بصوتك'}
          >
            {mic.state === 'transcribing' ? (
              <ActivityIndicator color={c.pr} />
            ) : mic.state === 'listening' ? (
              <StopIcon size={22} color={c.prt} weight="fill" />
            ) : (
              <MicrophoneIcon size={22} color={c.pr} />
            )}
          </Pressable>
          <Pressable onPress={send} disabled={busy || reading || !text.trim()} style={[styles.roundBtn, { backgroundColor: c.pr, opacity: busy || reading || !text.trim() ? 0.5 : 1 }]} accessibilityLabel="إرسال">
            <PaperPlaneTiltIcon size={22} color={c.prt} weight="fill" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

// A drug cited from the registry opens inside the app; a page from the web or an official
// document opens in the browser.
function openCitation(cite: AssistantAnswer['citations'][number]) {
  if (cite.kind === 'catalog') {
    const register = cite.source_id.slice('catalog:'.length);
    if (register) {
      router.push({ pathname: '/drug/[register]', params: { register } });
      return;
    }
  }
  if (cite.url) Linking.openURL(cite.url);
}

function AnswerCard({ answer, listening, onListen }: { answer: AssistantAnswer; listening: boolean; onListen: () => void }) {
  const { c } = useTheme();

  // Emergency: firm and first.
  if (answer.urgent)
    return (
      <View style={[styles.card, { backgroundColor: c.rds, borderColor: c.rd, borderWidth: 1.5 }]}>
        <Row gap={8}>
          <WarningIcon size={22} color={c.rd} weight="fill" />
          <T size={16} weight={700} color={c.rd}>
            موقف طارئ
          </T>
        </Row>
        <T>{answer.answer}</T>
      </View>
    );

  // note 2: advice questions get a calm redirect; no partial advice.
  if (answer.refused)
    return (
      <View style={[styles.card, { backgroundColor: c.sf, borderColor: c.pr, borderWidth: 1.5 }]}>
        <Row gap={8}>
          <FirstAidKitIcon size={20} color={c.pr} weight="fill" />
          <T size={16} weight={700}>
            هذا سؤال للصيدلي أو الطبيب
          </T>
        </Row>
        <T size={14} color={c.ink2}>
          {answer.answer}
        </T>
      </View>
    );

  const notFound = !answer.grounded && !answer.general;
  if (notFound)
    return (
      <Row gap={8} style={[styles.card, { backgroundColor: c.sf }, cardShadow]}>
        <MagnifyingGlassIcon size={20} color={c.ink} />
        <T weight={600} style={{ flex: 1 }}>
          {answer.answer}
        </T>
      </Row>
    );

  const documentCited = answer.citations.some((cite) => cite.kind === 'document');
  return (
    <View style={[styles.card, { backgroundColor: c.sf }, cardShadow]}>
      <T size={16} style={{ lineHeight: 28 }}>
        {answer.answer}
      </T>
      {answer.citations.length ? (
        <View style={styles.citations}>
          {answer.citations.map((cite) => (
            <Pressable
              key={cite.source_id}
              onPress={() => openCitation(cite)}
              style={[styles.citeChip, { backgroundColor: cite.kind === 'web' ? c.wns : c.prs }]}
            >
              {cite.kind === 'document' ? (
                <FileTextIcon size={14} color={c.pr} />
              ) : cite.kind === 'web' ? (
                <GlobeIcon size={14} color={c.wn} />
              ) : (
                <LinkSimpleIcon size={14} color={c.pr} />
              )}
              <T size={12.5} weight={600} color={cite.kind === 'web' ? c.wn : c.pr} numberOfLines={1} style={{ maxWidth: 240 }}>
                {`[${cite.number}] ${cite.title}`}
              </T>
            </Pressable>
          ))}
        </View>
      ) : null}
      {answer.web && answer.grounded ? (
        <Row gap={4}>
          <InfoIcon size={14} color={c.wn} weight="fill" />
          <T size={12} color={c.ink2}>
            جزء من الإجابة من الإنترنت وهو غير موثّق من الهيئة
          </T>
        </Row>
      ) : null}
      <Row style={{ justifyContent: 'space-between', marginTop: 2 }}>
        {answer.grounded ? (
          <Row gap={4}>
            <SealCheckIcon size={14} color={c.ok} weight="fill" />
            <T size={12} color={c.ink2}>
              {documentCited ? 'المصدر: هيئة الغذاء والدواء' : 'المصدر: بياناتنا الرسمية'}
            </T>
          </Row>
        ) : (
          <Row gap={4}>
            <InfoIcon size={14} color={c.wn} weight="fill" />
            <T size={12} color={c.ink2}>
              {answer.web ? 'معلومات من الإنترنت، غير موثّقة من الهيئة' : 'معلومة عامة، ليست من سجل الهيئة'}
            </T>
          </Row>
        )}
        <Pressable onPress={onListen} style={[styles.listen, { backgroundColor: c.bg }]} accessibilityLabel="استمع للإجابة">
          {listening ? <ActivityIndicator size="small" color={c.ink} /> : <SpeakerHighIcon size={16} color={c.ink} />}
          <T size={13} weight={600}>
            استمع
          </T>
        </Pressable>
      </Row>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  thread: { padding: 16, gap: 14 },
  attached: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, marginHorizontal: 12, marginTop: 6, padding: 8, borderWidth: 1, borderRadius: radius.md },
  thumb: { width: 52, height: 52, borderRadius: radius.sm },
  bubbleThumb: { width: 140, height: 140, borderRadius: radius.md, marginBottom: 8 },
  userBubble: { alignSelf: 'flex-end', maxWidth: '85%', borderRadius: radius.lg, borderTopRightRadius: 4, paddingVertical: 10, paddingHorizontal: 14 },
  pending: { alignSelf: 'flex-end', borderRadius: radius.lg, paddingVertical: 12, paddingHorizontal: 14 },
  card: { borderRadius: radius.lg, padding: 16, gap: 10 },
  citations: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  citeChip: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 10, borderRadius: radius.pill },
  listen: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 12, borderRadius: radius.pill, minHeight: 36 },
  mine: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, minHeight: 44, marginHorizontal: 16, marginTop: 8, paddingHorizontal: 14, borderWidth: 1, borderRadius: radius.md },
  suggestions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14 },
  inputBar: { flexDirection: 'row-reverse', alignItems: 'flex-end', gap: 8, paddingTop: 8, paddingHorizontal: 12 },
  input: { flex: 1, minWidth: 0, minHeight: 52, maxHeight: 120, borderRadius: radius.lg, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, textAlign: 'right', writingDirection: 'rtl' },
  roundBtn: { width: 52, height: 52, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center' },
});
