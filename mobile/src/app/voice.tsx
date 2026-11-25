// B5 · Voice search with transcript review: nothing is searched until the user taps "ابحث".
import { router } from 'expo-router';
import {
  ArrowCounterClockwiseIcon,
  ChatCircleDotsIcon,
  MagnifyingGlassIcon,
  MicrophoneIcon,
  PencilSimpleIcon,
  StopIcon,
  TranslateIcon,
  XIcon,
} from '@/components/icons';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { extractDrugName } from '@/api/client';
import { DisclaimerBar, Row, T } from '@/components/ui';
import { useRecentActions } from '@/state/recents';
import { useVoiceInput } from '@/state/voice';
import { cardShadow, fonts, radius, useTheme } from '@/theme';
import { SignInGate } from '@/components/SignInGate';

export default function VoiceSearch() {
  return (
    <SignInGate what="البحث الصوتي">
      <VoiceSearchScreen />
    </SignInGate>
  );
}

function VoiceSearchScreen() {
  const { c } = useTheme();
  const mic = useVoiceInput();
  const { add } = useRecentActions();
  const [heard, setHeard] = useState('');
  const [extracting, setExtracting] = useState(false);

  useEffect(() => {
    mic.start();
    // start listening as soon as the screen opens, like the wireframe
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finish = async () => {
    const text = await mic.stop();
    if (!text) return;
    setHeard(text);
    // "أنا عايز بنادول" is searched as "بنادول": the model picks the drug name out of the sentence.
    setExtracting(true);
    try {
      const { query } = await extractDrugName(text);
      if (query.trim()) setHeard(query.trim());
    } catch {
      // keep what was heard: the person can still edit it and search
    } finally {
      setExtracting(false);
    }
  };

  const retry = async () => {
    setHeard('');
    await mic.start();
  };

  const search = () => {
    const q = heard.trim();
    if (!q) return;
    add({ ar: q, en: null, register: null, query: q });
    router.replace({ pathname: '/search', params: { q } });
  };

  const askAssistant = () => {
    const q = heard.trim();
    if (q) router.replace({ pathname: '/assistant', params: { q } });
  };

  const listening = mic.state === 'listening';
  const transcribing = mic.state === 'transcribing' || extracting;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.iconBtn} accessibilityLabel="إغلاق">
          <XIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          بحث صوتي
        </T>
      </View>
      <DisclaimerBar />

      <View style={styles.body}>
        <Pressable
          onPress={listening ? finish : retry}
          disabled={transcribing}
          style={[styles.mic, { backgroundColor: listening ? c.pr : c.prs }]}
          accessibilityLabel={listening ? 'خلصت كلام' : 'ابدأ التسجيل'}
        >
          {transcribing ? (
            <ActivityIndicator size="large" color={c.pr} />
          ) : listening ? (
            <StopIcon size={44} color={c.prt} weight="fill" />
          ) : (
            <MicrophoneIcon size={48} color={c.pr} />
          )}
        </Pressable>
        <T size={18} weight={700} align="center">
          {listening ? 'جارٍ الاستماع… اضغط إذا خلصت' : transcribing ? 'نكتب اللي قلته…' : heard ? 'تمام، راجع اللي سمعناه' : 'اضغط على الميكروفون وتكلّم'}
        </T>
        {mic.error ? (
          <T size={14} color={c.rd} align="center">
            {mic.error}
          </T>
        ) : null}

        {/* note 1: the transcript is shown and editable; nothing is searched until "ابحث" */}
        <View style={[styles.transcript, { backgroundColor: c.sf }, cardShadow]}>
          <T size={13} color={c.ink2}>
            اسم الدواء (يمكنك التعديل)
          </T>
          <Row gap={8}>
            <TextInput
              value={heard}
              onChangeText={setHeard}
              placeholder="بيظهر هنا اللي قلته"
              placeholderTextColor={c.ink2}
              style={[styles.input, { color: c.ink, fontFamily: fonts.ar[600] }]}
            />
            <PencilSimpleIcon size={20} color={c.ink2} />
          </Row>
        </View>
        <Row gap={6}>
          <TranslateIcon size={16} color={c.ink2} />
          <T size={13} color={c.ink2}>
            نفهم اللهجتين السعودية والمصرية
          </T>
        </Row>
      </View>

      <View style={styles.actions}>
        <Pressable onPress={search} disabled={!heard.trim()} style={[styles.primary, { backgroundColor: c.pr, opacity: heard.trim() ? 1 : 0.5 }]}>
          <MagnifyingGlassIcon size={20} color={c.prt} />
          <T weight={700} color={c.prt}>
            ابحث
          </T>
        </Pressable>
        <Row gap={10}>
          <Pressable onPress={askAssistant} disabled={!heard.trim()} style={[styles.secondary, { borderColor: c.pr, opacity: heard.trim() ? 1 : 0.5 }]}>
            <ChatCircleDotsIcon size={20} color={c.pr} />
            <T weight={600} color={c.pr}>
              اسأل المساعد
            </T>
          </Pressable>
          <Pressable onPress={retry} disabled={listening || transcribing} style={[styles.secondary, { borderColor: c.pr }]}>
            <ArrowCounterClockwiseIcon size={20} color={c.pr} />
            <T weight={600} color={c.pr}>
              أعد المحاولة
            </T>
          </Pressable>
        </Row>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 18, paddingHorizontal: 20 },
  mic: { width: 120, height: 120, borderRadius: 60, alignItems: 'center', justifyContent: 'center' },
  transcript: { alignSelf: 'stretch', borderRadius: radius.lg, padding: 16, gap: 6 },
  input: { flex: 1, minWidth: 0, fontSize: 22, textAlign: 'right', writingDirection: 'rtl', paddingVertical: 4 },
  actions: { padding: 16, gap: 10 },
  primary: { minHeight: 52, borderRadius: radius.md, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  secondary: { flex: 1, minHeight: 48, borderRadius: radius.md, borderWidth: 1.5, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
});
