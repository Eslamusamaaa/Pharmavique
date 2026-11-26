// A shared conversation (ADR-022): anyone with the link, no account. Read only, as it was when it
// was shared; it ends when its owner deletes the conversation or stops sharing it.
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ApiError, friendlyError } from '@/api/client';
import { getShared, type SharedConversation } from '@/api/conversations';
import { AnswerCard } from '@/components/AnswerCard';
import { HistoryCard } from '@/components/history-card';
import { ArrowRightIcon, ShareNetworkIcon } from '@/components/icons';
import { DisclaimerBar, PrimaryButton, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

export default function SharedConversationPage() {
  const { c } = useTheme();
  const { token } = useLocalSearchParams<{ token: string }>();
  const [shared, setShared] = useState<SharedConversation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    getShared(token ?? '', abort.signal)
      .then(setShared)
      .catch((e) => {
        if ((e as Error).name === 'AbortError') return;
        setError(
          e instanceof ApiError && e.status === 404
            ? 'هالمحادثة ما عادت موجودة. يمكن صاحبها حذفها أو وقّف مشاركتها.'
            : friendlyError(e),
        );
      });
    return () => abort.abort();
  }, [token]);

  const day = shared
    ? new Date(shared.shared_at).toLocaleDateString('ar-SA-u-nu-latn', { year: 'numeric', month: 'long', day: 'numeric' })
    : '';

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <Row gap={8} style={styles.header}>
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))}
          style={styles.iconBtn}
          accessibilityRole="button"
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }} numberOfLines={1}>
          {shared?.title ?? 'محادثة متشاركة'}
        </T>
      </Row>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.thread}>
        {!shared && !error ? <ActivityIndicator color={c.ink2} /> : null}
        {error ? (
          <View style={{ gap: 14 }}>
            <T size={15} color={c.ink2}>
              {error}
            </T>
            <PrimaryButton label="افتح Pharmavique" onPress={() => router.navigate('/')} />
          </View>
        ) : null}
        {shared ? (
          <Row gap={6}>
            <ShareNetworkIcon size={14} color={c.ink2} />
            <T size={12.5} color={c.ink2} style={{ flex: 1 }}>
              {`محادثة مع مساعد Pharmavique، تمت مشاركتها في ${day}. للاطلاع فقط.`}
            </T>
          </Row>
        ) : null}
        {shared?.messages.map((m) =>
          m.role === 'user' ? (
            <View key={m.id} style={[styles.userBubble, { backgroundColor: c.pr }]}>
              <T color={c.prt} weight={500}>
                {m.text}
              </T>
            </View>
          ) : (
            <View key={m.id} style={{ gap: 10 }}>
              {m.answer ? <AnswerCard answer={m.answer} savedAt={m.created_at} /> : <T>{m.text}</T>}
              {m.answer?.history_check ? <HistoryCard check={m.answer.history_check} /> : null}
            </View>
          ),
        )}
        {shared ? (
          <View style={{ marginTop: 8 }}>
            <PrimaryButton label="اسأل المساعد بنفسك" outline onPress={() => router.navigate('/assistant')} />
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  header: { height: 52, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  thread: { padding: 16, gap: 14, paddingBottom: 48 },
  userBubble: { alignSelf: 'flex-end', maxWidth: '85%', borderRadius: radius.lg, borderTopRightRadius: 4, paddingVertical: 10, paddingHorizontal: 14 },
});
