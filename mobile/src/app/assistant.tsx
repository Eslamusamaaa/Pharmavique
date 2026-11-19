// B16 · Assistant: levels, cited answers, redirect, not found, listen (pharmavique-wireframes/PvB3).
import { router, useLocalSearchParams } from 'expo-router';
import {
  ArrowRightIcon,
  FileTextIcon,
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
} from 'phosphor-react-native';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { askAssistant, friendlyError, type AssistantAnswer, type Level } from '@/api/client';
import { DisclaimerBar, Row, T } from '@/components/ui';
import { useSpeaker, useVoiceInput } from '@/state/voice';
import { cardShadow, fonts, radius, useTheme } from '@/theme';

type Turn =
  | { id: string; role: 'user'; text: string }
  | { id: string; role: 'assistant'; answer: AssistantAnswer }
  | { id: string; role: 'pending' }
  | { id: string; role: 'error'; text: string };

const LEVELS: { key: Level; label: string }[] = [
  { key: 'patient', label: 'مبسّط' },
  { key: 'pharmacist', label: 'للصيدلي' },
  { key: 'clinical', label: 'متخصص' },
];

const SUGGESTIONS = ['ما سعر بانادول 500؟', 'ما المواد الفعالة في بانادول اكسترا؟', 'هل فيه بديل بنفس المادة؟'];

let counter = 0;
const nextId = () => `t${++counter}`;

export default function Assistant() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  const params = useLocalSearchParams<{ register?: string; name?: string; q?: string }>();
  const [level, setLevel] = useState<Level>('patient');
  const [text, setText] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const mic = useVoiceInput();
  const speaker = useSpeaker();
  const busy = turns.some((t) => t.role === 'pending');

  const ask = async (question: string, spoken = false) => {
    const q = question.trim();
    if (!q || busy) return;
    const pendingId = nextId();
    setText('');
    setTurns((all) => [...all, { id: nextId(), role: 'user', text: q }, { id: pendingId, role: 'pending' }]);
    try {
      const answer = await askAssistant({ question: q, level, register_number: params.register ?? null, spoken });
      setTurns((all) => all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'assistant', answer } : t)));
      // A question asked by voice is answered by voice too (Saudi Arabic).
      if (spoken && !answer.refused) speaker.speak(pendingId, answer.answer);
    } catch (e) {
      setTurns((all) => all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'error', text: friendlyError(e) } : t)));
    }
  };

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
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.navigate('/(tabs)/index'))} style={styles.iconBtn} accessibilityLabel="رجوع">
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }} numberOfLines={1}>
          {params.name ? `اسأل عن ${params.name}` : 'اسأل عن بيانات الأدوية'}
        </T>
      </View>
      <DisclaimerBar />

      {/* note 3: answer level; same sources at every level, only wording and depth change */}
      <View style={[styles.segment, { backgroundColor: c.sf }, cardShadow]}>
        {LEVELS.map((l) => (
          <Pressable key={l.key} onPress={() => setLevel(l.key)} style={[styles.segmentItem, level === l.key && { backgroundColor: c.pr }]}>
            <T size={14} weight={level === l.key ? 700 : 400} color={level === l.key ? c.prt : c.ink2} align="center">
              {l.label}
            </T>
          </Pressable>
        ))}
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={{ flex: 1 }}>
        <ScrollView ref={scroll} contentContainerStyle={styles.thread} keyboardShouldPersistTaps="handled">
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
              <AnswerCard
                key={turn.id}
                answer={turn.answer}
                listening={speaker.loadingId === turn.id}
                onListen={() => speaker.speak(turn.id, turn.answer.answer)}
              />
            );
          })}
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
          <View style={styles.suggestions}>
            {SUGGESTIONS.map((s) => (
              <Pressable key={s} onPress={() => ask(s)} style={[styles.chip, { backgroundColor: c.sf, borderColor: c.ln }]}>
                <T size={14}>{s}</T>
              </Pressable>
            ))}
          </View>
        </ScrollView>

        <View style={[styles.inputBar, { backgroundColor: c.bg, paddingBottom: Math.max(insets.bottom, 12) }]}>
          <TextInput
            value={text}
            onChangeText={setText}
            onSubmitEditing={() => ask(text)}
            placeholder={mic.state === 'listening' ? 'بنسمعك… دوس تاني لما تخلص' : 'اكتب أو تكلّم عن اسم أو مادة أو سعر'}
            placeholderTextColor={c.ink2}
            multiline
            style={[styles.input, { backgroundColor: c.sf, color: c.ink, fontFamily: fonts.ar[400] }, cardShadow]}
          />
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
          <Pressable onPress={() => ask(text)} disabled={busy || !text.trim()} style={[styles.roundBtn, { backgroundColor: c.pr, opacity: busy || !text.trim() ? 0.5 : 1 }]} accessibilityLabel="إرسال">
            <PaperPlaneTiltIcon size={22} color={c.prt} weight="fill" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
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
              onPress={() => (cite.url ? Linking.openURL(cite.url) : undefined)}
              style={[styles.citeChip, { backgroundColor: c.prs }]}
            >
              {cite.kind === 'document' ? <FileTextIcon size={14} color={c.pr} /> : <LinkSimpleIcon size={14} color={c.pr} />}
              <T size={12.5} weight={600} color={c.pr} numberOfLines={1} style={{ maxWidth: 240 }}>
                {`[${cite.number}] ${cite.title}`}
              </T>
            </Pressable>
          ))}
        </View>
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
              معلومة عامة، مش من سجل الهيئة
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
  segment: { flexDirection: 'row-reverse', borderRadius: radius.md, padding: 3, marginHorizontal: 16, marginTop: 12 },
  segmentItem: { flex: 1, minHeight: 40, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  thread: { padding: 16, gap: 14 },
  userBubble: { alignSelf: 'flex-end', maxWidth: '85%', borderRadius: radius.lg, borderTopRightRadius: 4, paddingVertical: 10, paddingHorizontal: 14 },
  pending: { alignSelf: 'flex-end', borderRadius: radius.lg, paddingVertical: 12, paddingHorizontal: 14 },
  card: { borderRadius: radius.lg, padding: 16, gap: 10 },
  citations: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  citeChip: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 10, borderRadius: radius.pill },
  listen: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 12, borderRadius: radius.pill, minHeight: 36 },
  suggestions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14 },
  inputBar: { flexDirection: 'row-reverse', alignItems: 'flex-end', gap: 8, paddingTop: 8, paddingHorizontal: 12 },
  input: { flex: 1, minWidth: 0, minHeight: 52, maxHeight: 120, borderRadius: radius.lg, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, textAlign: 'right', writingDirection: 'rtl' },
  roundBtn: { width: 52, height: 52, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center' },
});
