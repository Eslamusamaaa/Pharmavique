// B16 · Assistant: levels, cited answers, redirect, not found, listen (pharmavique-wireframes/PvB3).
import { router, useLocalSearchParams } from 'expo-router';
import {
  ArrowCounterClockwiseIcon,
  ArrowRightIcon,
  CameraIcon,
  ChatsIcon,
  MicrophoneIcon,
  PaperPlaneTiltIcon,
  PlusIcon,
  StopIcon,
  XIcon,
} from '@/components/icons';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
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
  ApiError,
  askAssistant,
  friendlyError,
  scanImage,
  type AssistantAnswer,
  type ConversationTurn,
} from '@/api/client';
import { getConversation, writeTitle, type SavedMessage } from '@/api/conversations';
import { AnswerCard } from '@/components/AnswerCard';
import { ConversationList } from '@/components/ConversationList';
import { HistoryCard } from '@/components/history-card';
import { useAccount } from '@/state/auth';
import { DisclaimerBar, Row, T } from '@/components/ui';
import { roleInfo, useRole } from '@/state/role';
import { useSpeaker, useVoiceInput } from '@/state/voice';
import { cardShadow, fonts, radius, useTheme } from '@/theme';
import { SignInGate } from '@/components/SignInGate';

type Turn =
  | { id: string; role: 'user'; text: string; sent?: string; photo?: string }
  | { id: string; role: 'assistant'; answer: AssistantAnswer; savedAt?: string }
  | { id: string; role: 'pending' }
  // `retry`: the question to send again ("try again"); a saved one replaces its failed copy
  | { id: string; role: 'error'; text: string; retry?: string };

let counter = 0;
const nextId = () => `t${++counter}`;
// the question a photo carries when it is sent without one (Saudi dialect)
const PHOTO_ONLY_QUESTION = 'وش هذا الدواء؟';
const NO_ANSWER = 'ما وصلت الإجابة. جرّب مرة ثانية.';

/** A saved conversation as turns on screen: answers as they were shown, with their dates. */
function savedTurns(messages: SavedMessage[]): Turn[] {
  return messages.flatMap((m): Turn[] => {
    if (m.role === 'assistant')
      return [
        {
          id: nextId(),
          role: 'assistant',
          savedAt: m.created_at,
          answer: m.answer ?? {
            answer: m.text,
            citations: [],
            grounded: false,
            web: false,
            general: true,
            urgent: false,
            refused: false,
            level: 'patient',
            tools_used: [],
          },
        },
      ];
    const question: Turn = { id: nextId(), role: 'user', text: m.text, sent: m.text };
    return m.status === 'ok' ? [question] : [question, { id: nextId(), role: 'error', text: NO_ANSWER, retry: m.text }];
  });
}

export default function Assistant() {
  return (
    <SignInGate what="المساعد">
      <AssistantScreen />
    </SignInGate>
  );
}

function AssistantScreen() {
  const { c } = useTheme();
  const insets = useSafeAreaInsets();
  // `c`: a saved conversation to open; `list=1`: open the list of saved conversations
  const params = useLocalSearchParams<{ register?: string; name?: string; q?: string; c?: string; list?: string }>();
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
  // true while the text in the box came from the microphone: its answer is spoken too
  const [spokenDraft, setSpokenDraft] = useState(false);
  const readingNow = useRef(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [opening, setOpening] = useState(false);

  const newConversation = () => {
    setTurns([]);
    setConversationId(null);
  };

  const openConversation = async (id: string) => {
    setOpening(true);
    try {
      const { messages } = await getConversation(id);
      setTurns(savedTurns(messages));
      setConversationId(id);
    } catch (e) {
      setTurns([{ id: nextId(), role: 'error', text: friendlyError(e) }]);
      setConversationId(null);
    } finally {
      setOpening(false);
    }
  };

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
    setSpokenDraft(false);
    Keyboard.dismiss(); // the answer is what matters now, not the keyboard
    setTurns((all) => [...all, { id: nextId(), role: 'user', text: shown ?? q, sent: q, photo: photoUri }, { id: pendingId, role: 'pending' }]);
    try {
      const answer = await askAssistant({
        question: q,
        level,
        register_number: params.register ?? null,
        spoken,
        history,
        conversation_id: conversationId,
        use_history: !!(useMine && account && params.register),
      });
      setTurns((all) => all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'assistant', answer } : t)));
      if (answer.conversation_id) {
        setConversationId(answer.conversation_id);
        // a new conversation is named by the model after its first answer; never waited for
        if (answer.new_conversation) writeTitle(answer.conversation_id).catch(() => undefined);
      }
      // A question asked by voice is answered by voice too (Saudi Arabic).
      if (spoken && !answer.refused) speaker.speak(pendingId, answer.answer);
    } catch (e) {
      if (e instanceof ApiError && e.conversationId) setConversationId(e.conversationId);
      setTurns((all) =>
        all.map((t) => (t.id === pendingId ? { id: pendingId, role: 'error', text: friendlyError(e), retry: q } : t)),
      );
    }
  };

  // "Try again": the failed question and its error leave the screen and the question is asked again
  // (in a saved conversation the server replaces the failed copy instead of adding another).
  const retry = (errorId: string, question: string) => {
    if (busy) return;
    setTurns((all) => {
      const at = all.findIndex((t) => t.id === errorId);
      const before = all[at - 1];
      return all.filter((t, i) => i !== at && !(i === at - 1 && before?.role === 'user'));
    });
    ask(question);
  };

  // A photo stays attached until the person adds the question to send with it. The box scan only
  // transcribes what is printed on the box; the name it read joins the question. No image goes to
  // the assistant's language model (ADR-017).
  const attach = (picked: ImagePicker.ImagePickerResult) => {
    const asset = picked.assets?.[0];
    if (picked.canceled || !asset) return;
    setPhoto({ uri: asset.uri, mimeType: asset.mimeType ?? 'image/jpeg' });
  };

  // A photo can go alone (the question is then what the medicine is), or with a written or spoken
  // question.
  const sendWithPhoto = async () => {
    const attached = photo;
    const asked = text.trim() || PHOTO_ONLY_QUESTION;
    const spoken = spokenDraft;
    if (!attached || readingNow.current || busy) return;
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
مكتوب على العلبة (مقروء من صورة): "${printed}"`, spoken, asked, attached.uri);
    } catch (e) {
      // the photo stays attached so the person can send again
      setTurns((all) => [...all, { id: nextId(), role: 'error', text: friendlyError(e) }]);
    } finally {
      readingNow.current = false;
      setReading(false);
    }
  };

  const send = () => (photo ? sendWithPhoto() : ask(text, spokenDraft));

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
    if (params.c) openConversation(params.c);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.c]);

  useEffect(() => {
    if (params.list === '1' && account) setListOpen(true);
  }, [params.list, account]);

  useEffect(() => {
    setTimeout(() => scroll.current?.scrollToEnd({ animated: true }), 50);
  }, [turns]);

  // What was said goes into the box, not straight to the assistant: the person can read it, fix
  // it, add a photo, and send them together (or send the words alone).
  const onMic = async () => {
    if (mic.state === 'listening') {
      const heard = (await mic.stop())?.trim();
      if (heard) {
        setText((typed) => (typed.trim() ? `${typed.trim()} ${heard}` : heard));
        setSpokenDraft(true);
      }
    } else if (mic.state === 'idle') {
      await mic.start();
    }
  };

  const canSend = !busy && !reading && mic.state !== 'transcribing' && (!!text.trim() || !!photo);

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))} style={styles.iconBtn} accessibilityLabel="رجوع">
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }} numberOfLines={1}>
          {params.name ? `اسأل عن ${params.name}` : 'اسأل عن بيانات الأدوية'}
        </T>
        {account ? (
          <>
            <Pressable onPress={newConversation} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel="محادثة جديدة">
              <PlusIcon size={22} color={c.ink} />
            </Pressable>
            <Pressable onPress={() => setListOpen(true)} style={styles.iconBtn} accessibilityRole="button" accessibilityLabel="محادثاتي">
              <ChatsIcon size={24} color={c.ink} />
            </Pressable>
          </>
        ) : null}
      </View>
      {account ? (
        <ConversationList
          visible={listOpen}
          onClose={() => setListOpen(false)}
          currentId={conversationId}
          onOpen={openConversation}
          onNew={newConversation}
          level={level}
        />
      ) : null}
      <DisclaimerBar />
      {account && params.register ? (
        <Pressable
          onPress={() => setUseMine((v) => !v)}
          style={[styles.mine, { backgroundColor: useMine ? c.prs : c.sf, borderColor: useMine ? c.pr : c.ln }]}
          accessibilityRole="switch"
          aria-checked={useMine}
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
          {opening ? <ActivityIndicator color={c.ink2} /> : null}
          {turns.length === 0 && !opening ? (
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
                  {turn.retry ? (
                    <Pressable
                      onPress={() => retry(turn.id, turn.retry as string)}
                      disabled={busy}
                      style={[styles.retry, { borderColor: c.pr, opacity: busy ? 0.5 : 1 }]}
                      accessibilityRole="button"
                    >
                      <ArrowCounterClockwiseIcon size={16} color={c.pr} />
                      <T size={14} weight={600} color={c.pr}>
                        حاول مرة ثانية
                      </T>
                    </Pressable>
                  ) : null}
                </View>
              );
            return (
              <View key={turn.id} style={{ gap: 10 }}>
                <AnswerCard
                  answer={turn.answer}
                  listening={speaker.loadingId === turn.id}
                  onListen={() => speaker.speak(turn.id, turn.answer.answer)}
                  savedAt={turn.savedAt}
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
          {turns.length === 0 && !opening ? (
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
              صورة مرفقة. اكتب أو قل سؤالك عنها، أو أرسلها كذا.
            </T>
            <Pressable onPress={() => setPhoto(null)} accessibilityLabel="أزل الصورة" style={styles.iconBtn}>
              <XIcon size={20} color={c.ink2} />
            </Pressable>
          </View>
        ) : null}

        <View style={[styles.inputBar, { backgroundColor: c.bg, paddingBottom: Math.max(insets.bottom, 12) }]}>
          <TextInput
            value={text}
            onChangeText={(typed) => {
              setText(typed);
              if (!typed.trim()) setSpokenDraft(false);
            }}
            onSubmitEditing={send}
            placeholder={
              mic.state === 'listening'
                ? 'نسمعك… اضغط مرة ثانية إذا خلصت'
                : photo
                  ? 'اكتب أو قل سؤالك عن الصورة (اختياري)'
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
          <Pressable onPress={send} disabled={!canSend} style={[styles.roundBtn, { backgroundColor: c.pr, opacity: canSend ? 1 : 0.5 }]} accessibilityLabel="إرسال">
            <PaperPlaneTiltIcon size={22} color={c.prt} weight="fill" />
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
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
  retry: { flexDirection: 'row-reverse', alignItems: 'center', alignSelf: 'flex-start', gap: 6, borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14, minHeight: 44 },
  mine: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, minHeight: 44, marginHorizontal: 16, marginTop: 8, paddingHorizontal: 14, borderWidth: 1, borderRadius: radius.md },
  suggestions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, marginTop: 6 },
  chip: { borderWidth: 1, borderRadius: radius.pill, paddingVertical: 8, paddingHorizontal: 14 },
  inputBar: { flexDirection: 'row-reverse', alignItems: 'flex-end', gap: 8, paddingTop: 8, paddingHorizontal: 12 },
  input: { flex: 1, minWidth: 0, minHeight: 52, maxHeight: 120, borderRadius: radius.lg, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, textAlign: 'right', writingDirection: 'rtl' },
  roundBtn: { width: 52, height: 52, borderRadius: radius.lg, alignItems: 'center', justifyContent: 'center' },
});
