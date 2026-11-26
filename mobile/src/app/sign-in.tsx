// Sign in or create an account. Search and the assistant work without one; an account is for saved
// medicines, alerts and the pharmacist and company views.
import { router } from 'expo-router';
import { ArrowRightIcon } from '@/components/icons';
import { useRef, useState, type ComponentRef } from 'react';
import { ActivityIndicator, Keyboard, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, AuthError, resendCode, signIn, signUp } from '@/api/auth';
import { FormScroll } from '@/components/FormScroll';
import { DisclaimerBar, T } from '@/components/ui';
import { ROLES, type Role } from '@/state/role';
import { radius, useTheme } from '@/theme';

export default function SignIn() {
  const { c } = useTheme();
  const [mode, setMode] = useState<'in' | 'up'>('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<Role>('patient');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const passwordField = useRef<ComponentRef<typeof TextInput>>(null);

  const submit = async () => {
    if (busy) return;
    Keyboard.dismiss();
    setBusy(true);
    setError(null);
    try {
      if (mode === 'in') {
        await signIn(email, password);
      } else {
        const made = await signUp(email, password, role);
        router.replace({ pathname: '/verify-email', params: { email: made.email } });
        return;
      }
      if (router.canGoBack()) router.back();
      else router.replace('/account');
    } catch (e) {
      if (e instanceof AuthError && e.kind === 'email_not_verified') {
        // right password, address not confirmed yet: send a fresh code and ask for it
        await resendCode(email.trim()).catch(() => undefined);
        router.replace({ pathname: '/verify-email', params: { email: email.trim().toLowerCase() } });
        return;
      }
      setError(arabicAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const field = [styles.input, { borderColor: c.ink2, color: c.ink, backgroundColor: c.sf }];

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.topBar}>
        <Pressable
          onPress={() => (router.canGoBack() ? router.back() : router.replace('/account'))}
          style={styles.iconBtn}
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          {mode === 'in' ? 'تسجيل الدخول' : 'إنشاء حساب'}
        </T>
      </View>
      <DisclaimerBar />
      <FormScroll contentStyle={styles.content}>
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
          returnKeyType="next"
          submitBehavior="submit"
          onSubmitEditing={() => passwordField.current?.focus()}
          style={field}
        />
        <TextInput
          ref={passwordField}
          value={password}
          onChangeText={setPassword}
          placeholder="كلمة المرور (10 حروف على الأقل)"
          placeholderTextColor={c.ink2}
          secureTextEntry
          returnKeyType="done"
          onSubmitEditing={() => Keyboard.dismiss()}
          autoCapitalize="none"
          textContentType={mode === 'in' ? 'password' : 'newPassword'}
          autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
          style={field}
        />

        {mode === 'up' ? (
          <View style={{ gap: 8 }}>
            <T size={14} weight={600}>
              وش دورك؟
            </T>
            {ROLES.map((r) => (
              <Pressable
                key={r.key}
                onPress={() => setRole(r.key)}
                style={[styles.role, { borderColor: role === r.key ? c.pr : c.ink2, backgroundColor: role === r.key ? c.prs : c.sf }]}
                accessibilityRole="radio"
                aria-selected={role === r.key}
              >
                <T weight={600}>{r.label}</T>
                <T size={13} color={c.ink2}>
                  {r.hint}
                </T>
              </Pressable>
            ))}
            <T size={12.5} color={c.ink2}>
              اختيارك للدور يحدد الشاشات اللي بتظهر لك. للحين ما فيه توثيق للصيدلي أو الشركة، وما أحد يشوف بيانات أحد ثاني.
            </T>
          </View>
        ) : null}

        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}

        <Pressable
          onPress={submit}
          disabled={busy || !email.trim() || !password}
          style={[styles.main, { backgroundColor: c.pr, opacity: busy || !email.trim() || !password ? 0.6 : 1 }]}
          accessibilityRole="button"
        >
          {busy ? (
            <ActivityIndicator color={c.prt} />
          ) : (
            <T weight={700} color={c.prt}>
              {mode === 'in' ? 'دخول' : 'إنشاء الحساب'}
            </T>
          )}
        </Pressable>

        {mode === 'in' ? (
          <Pressable
            onPress={() => {
              Keyboard.dismiss();
              router.replace({ pathname: '/forgot-password', params: { email: email.trim() } });
            }}
            style={{ minHeight: 44, justifyContent: 'center' }}
            accessibilityRole="link"
          >
            <T size={14} weight={600} color={c.pr} align="center">
              نسيت كلمة المرور؟
            </T>
          </Pressable>
        ) : null}

        <Pressable
          onPress={() => {
            Keyboard.dismiss();
            setMode(mode === 'in' ? 'up' : 'in');
            setError(null);
          }}
          style={{ minHeight: 44, justifyContent: 'center' }}
        >
          <T size={14} weight={600} color={c.pr} align="center">
            {mode === 'in' ? 'ما عندك حساب؟ أنشئ حساب' : 'عندك حساب؟ سجّل الدخول'}
          </T>
        </Pressable>
      </FormScroll>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14 },
  input: { minHeight: 52, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 16, textAlign: 'right' },
  role: { borderWidth: 1.5, borderRadius: radius.md, padding: 12, gap: 2 },
  main: { minHeight: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
