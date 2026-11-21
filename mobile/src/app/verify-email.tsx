// Confirm the email with the six-digit code that was sent to it. There is no session until then.
import { router, useLocalSearchParams } from 'expo-router';
import { ArrowRightIcon } from 'phosphor-react-native';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, resendCode, verifyEmail } from '@/api/auth';
import { DisclaimerBar, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

const WAIT_SECONDS = 60; // the server does not send a new code sooner than this

export default function VerifyEmail() {
  const { c } = useTheme();
  const { email = '' } = useLocalSearchParams<{ email?: string }>();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [wait, setWait] = useState(WAIT_SECONDS);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const submit = async () => {
    if (busy || code.trim().length < 6) return;
    setBusy(true);
    setError(null);
    try {
      await verifyEmail(email, code);
      router.replace('/account');
    } catch (e) {
      setError(arabicAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const again = async () => {
    if (wait > 0) return;
    setError(null);
    setNote('لو الإيميل ده عليه حساب محتاج رمز، هيوصله رمز جديد.');
    setCode('');
    setWait(WAIT_SECONDS);
    await resendCode(email).catch(() => undefined);
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.topBar}>
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/sign-in'))}
          style={styles.iconBtn}
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          تأكيد الإيميل
        </T>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <T>
          بعتنا رمز من 6 أرقام على
        </T>
        <T weight={700} latin align="left">
          {email}
        </T>
        <T size={13} color={c.ink2}>
          الرمز صالح 10 دقايق. لو ماوصلش شوف مجلد الرسائل غير المرغوبة.
        </T>
        <TextInput
          value={code}
          onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
          placeholder="------"
          placeholderTextColor={c.ink2}
          keyboardType="number-pad"
          textContentType="oneTimeCode"
          autoComplete="one-time-code"
          maxLength={6}
          style={[styles.input, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }]}
          accessibilityLabel="رمز التأكيد"
        />
        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}
        {note ? (
          <T size={13} color={c.ink2} align="center">
            {note}
          </T>
        ) : null}
        <Pressable
          onPress={submit}
          disabled={busy || code.length < 6}
          style={[styles.main, { backgroundColor: c.pr, opacity: busy || code.length < 6 ? 0.6 : 1 }]}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color={c.prt} />
          ) : (
            <T weight={700} color={c.prt}>
              تأكيد
            </T>
          )}
        </Pressable>
        <Pressable onPress={again} disabled={wait > 0} style={{ minHeight: 44, justifyContent: 'center' }} accessibilityRole="button">
          <T size={14} weight={600} color={wait > 0 ? c.ink2 : c.pr} align="center">
            {wait > 0 ? `إعادة إرسال الرمز بعد ${wait} ثانية` : 'إعادة إرسال الرمز'}
          </T>
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14 },
  input: {
    minHeight: 60,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    fontSize: 28,
    letterSpacing: 8,
    textAlign: 'center',
  },
  main: { minHeight: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
