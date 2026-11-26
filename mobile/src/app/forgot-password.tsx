// Forgot password: the email gets a six-digit code, then the code and a new password sign the person in.
// The first step answers the same whether or not the address has an account, so it never reveals one.
import { router, useLocalSearchParams } from 'expo-router';
import { ArrowRightIcon } from '@/components/icons';
import { useEffect, useRef, useState, type ComponentRef } from 'react';
import { ActivityIndicator, Keyboard, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, forgotPassword, resetPassword } from '@/api/auth';
import { FormScroll } from '@/components/FormScroll';
import { DisclaimerBar, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

const WAIT_SECONDS = 60; // the server does not send a new code sooner than this

export default function ForgotPassword() {
  const { c } = useTheme();
  const params = useLocalSearchParams<{ email?: string }>();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState(params.email ?? '');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const passwordField = useRef<ComponentRef<typeof TextInput>>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const timer = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const sendCode = async () => {
    if (busy || !email.trim()) return;
    Keyboard.dismiss();
    setBusy(true);
    setError(null);
    try {
      await forgotPassword(email);
      setStep('code');
      setWait(WAIT_SECONDS);
    } catch (e) {
      setError(arabicAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const again = async () => {
    if (wait > 0 || busy) return;
    setError(null);
    setCode('');
    setWait(WAIT_SECONDS);
    await forgotPassword(email).catch(() => undefined);
  };

  const submit = async () => {
    if (busy || code.length < 6 || !password) return;
    Keyboard.dismiss();
    setBusy(true);
    setError(null);
    try {
      await resetPassword(email, code, password);
      // signed in: back to where sign-in was opened from, else the account
      if (router.canGoBack()) router.back();
      else router.replace('/account');
    } catch (e) {
      setError(arabicAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const field = [styles.input, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }];
  const ready = step === 'email' ? !!email.trim() : code.length === 6 && !!password;

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
          نسيت كلمة المرور
        </T>
      </View>
      <DisclaimerBar />
      <FormScroll contentStyle={styles.content}>
        {step === 'email' ? (
          <>
            <T>اكتب إيميل حسابك وبنرسل لك رمز من 6 أرقام لتغيير كلمة المرور.</T>
            <TextInput
              value={email}
              onChangeText={setEmail}
              placeholder="الإيميل"
              placeholderTextColor={c.ink2}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              textContentType="emailAddress"
              autoComplete="email"
              returnKeyType="done"
              onSubmitEditing={sendCode}
              style={field}
              accessibilityLabel="الإيميل"
            />
          </>
        ) : (
          <>
            <T>إذا هذا الإيميل عليه حساب، أرسلنا له رمز من 6 أرقام:</T>
            <T weight={700} latin align="left">
              {email.trim()}
            </T>
            <T size={13} color={c.ink2}>
              الرمز صالح 10 دقائق. إذا ما وصلك شوف مجلد الرسائل غير المرغوبة.
            </T>
            <TextInput
              value={code}
              onChangeText={(v) => {
                const digits = v.replace(/\D/g, '').slice(0, 6);
                setCode(digits);
                if (digits.length === 6) passwordField.current?.focus();
              }}
              placeholder="------"
              placeholderTextColor={c.ink2}
              keyboardType="number-pad"
              textContentType="oneTimeCode"
              autoComplete="one-time-code"
              maxLength={6}
              style={[styles.input, styles.codeInput, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }]}
              accessibilityLabel="رمز التأكيد"
            />
            <TextInput
              ref={passwordField}
              value={password}
              onChangeText={setPassword}
              placeholder="كلمة المرور الجديدة (10 حروف على الأقل)"
              placeholderTextColor={c.ink2}
              secureTextEntry
              autoCapitalize="none"
              textContentType="newPassword"
              autoComplete="new-password"
              returnKeyType="done"
              onSubmitEditing={submit}
              style={field}
              accessibilityLabel="كلمة المرور الجديدة"
            />
          </>
        )}

        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}

        <Pressable
          onPress={step === 'email' ? sendCode : submit}
          disabled={busy || !ready}
          style={[styles.main, { backgroundColor: c.pr, opacity: busy || !ready ? 0.6 : 1 }]}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color={c.prt} />
          ) : (
            <T weight={700} color={c.prt}>
              {step === 'email' ? 'أرسل الرمز' : 'غيّر كلمة المرور'}
            </T>
          )}
        </Pressable>

        {step === 'code' ? (
          <Pressable onPress={again} disabled={wait > 0} style={{ minHeight: 44, justifyContent: 'center' }} accessibilityRole="button">
            <T size={14} weight={600} color={wait > 0 ? c.ink2 : c.pr} align="center">
              {wait > 0 ? `إعادة إرسال الرمز بعد ${wait} ثانية` : 'إعادة إرسال الرمز'}
            </T>
          </Pressable>
        ) : null}
      </FormScroll>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14 },
  input: { minHeight: 52, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 16, textAlign: 'right' },
  codeInput: { minHeight: 60, fontSize: 28, letterSpacing: 8, textAlign: 'center' },
  main: { minHeight: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
