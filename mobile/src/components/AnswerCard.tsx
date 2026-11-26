// One assistant answer: the text, its citations and trust grades, where it came from, and "listen".
// Used by the assistant screen and by a shared conversation's page.
import { router } from 'expo-router';
import {
  ClockCounterClockwiseIcon,
  FileTextIcon,
  FirstAidKitIcon,
  GlobeIcon,
  InfoIcon,
  LinkSimpleIcon,
  MagnifyingGlassIcon,
  SealCheckIcon,
  SpeakerHighIcon,
  WarningIcon,
} from '@/components/icons';
import { ActivityIndicator, Linking, Pressable, StyleSheet, View } from 'react-native';

import type { AssistantAnswer } from '@/api/client';
import { Row, T, TrustBadge } from '@/components/ui';
import { cardShadow, radius, useTheme } from '@/theme';

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

/** "إجابة بتاريخ ..." for an answer read again later: the registry may have changed since. */
export function SavedOn({ at }: { at: string }) {
  const { c } = useTheme();
  const day = new Date(at).toLocaleDateString('ar-SA-u-nu-latn', { year: 'numeric', month: 'long', day: 'numeric' });
  return (
    <Row gap={4}>
      <ClockCounterClockwiseIcon size={14} color={c.ink2} />
      <T size={12} color={c.ink2} style={{ flex: 1 }}>
        {`إجابة بتاريخ ${day}، يمكن البيانات تغيّرت بعدها`}
      </T>
    </Row>
  );
}

export function AnswerCard({
  answer,
  listening = false,
  onListen,
  savedAt,
}: {
  answer: AssistantAnswer;
  listening?: boolean;
  onListen?: () => void;
  savedAt?: string; // set when the answer is read again from a saved conversation
}) {
  const { c } = useTheme();
  const saved = savedAt ? <SavedOn at={savedAt} /> : null;

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
        {saved}
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
        {saved}
      </View>
    );

  const notFound = !answer.grounded && !answer.general;
  if (notFound)
    return (
      <View style={[styles.card, { backgroundColor: c.sf }, cardShadow]}>
        <Row gap={8}>
          <MagnifyingGlassIcon size={20} color={c.ink} />
          <T weight={600} style={{ flex: 1 }}>
            {answer.answer}
          </T>
        </Row>
        {saved}
      </View>
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
              accessibilityRole="link"
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
      {answer.citations.length ? (
        <Row gap={6} style={{ flexWrap: 'wrap' }}>
          {Array.from(new Set(answer.citations.map((cite) => cite.trust_grade ?? 'unverified'))).map((grade) => (
            <TrustBadge
              key={grade}
              grade={grade}
              label={answer.citations.find((cite) => (cite.trust_grade ?? 'unverified') === grade)?.trust_label_ar}
            />
          ))}
        </Row>
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
        {onListen ? (
          <Pressable onPress={onListen} style={[styles.listen, { backgroundColor: c.bg }]} accessibilityRole="button" accessibilityLabel="استمع للإجابة">
            {listening ? <ActivityIndicator size="small" color={c.ink} /> : <SpeakerHighIcon size={16} color={c.ink} />}
            <T size={13} weight={600}>
              استمع
            </T>
          </Pressable>
        ) : null}
      </Row>
      {saved}
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: radius.lg, padding: 16, gap: 10 },
  citations: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  citeChip: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 10, borderRadius: radius.pill },
  listen: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 6, paddingHorizontal: 12, borderRadius: radius.pill, minHeight: 36 },
});
