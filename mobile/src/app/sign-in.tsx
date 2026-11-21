// Sign in or create an account. Search and the assistant work without one; an account is for saved
// medicines, alerts and the pharmacist and company views.
import { router } from 'expo-router';
import { ArrowRightIcon } from 'phosphor-react-native';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, signIn, signUp } from '@/api/auth';
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

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === 'in') await signIn(email, password);
      else await signUp(email, password, role);
      if (router.canGoBack()) router.back();
      else router.replace('/account');
    } catch (e) {
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
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
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
          style={field}
        />
        <TextInput
          value={password}
          onChangeText={setPassword}
          placeholder="كلمة المرور (10 حروف على الأقل)"
          placeholderTextColor={c.ink2}
          secureTextEntry
          autoCapitalize="none"
          textContentType={mode === 'in' ? 'password' : 'newPassword'}
          autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
          style={field}
        />

        {mode === 'up' ? (
          <View style={{ gap: 8 }}>
            <T size={14} weight={600}>
              أنت مين؟
            </T>
            {ROLES.map((r) => (
              <Pressable
                key={r.key}
                onPress={() => setRole(r.key)}
                style={[styles.role, { borderColor: role === r.key ? c.pr : c.ink2, backgroundColor: role === r.key ? c.prs : c.sf }]}
                accessibilityRole="radio"
                accessibilityState={{ selected: role === r.key }}
              >
                <T weight={600}>{r.label}</T>
                <T size={13} color={c.ink2}>
                  {r.hint}
                </T>
              </Pressable>
            ))}
            <T size={12.5} color={c.ink2}>
              اختيارك للدور بيحدد الشاشات اللي هتظهر لك. لسه مفيش توثيق للصيدلي أو الشركة، ومفيش حد بيشوف بيانات حد تاني.
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

        <Pressable
          onPress={() => {
            setMode(mode === 'in' ? 'up' : 'in');
            setError(null);
          }}
          style={{ minHeight: 44, justifyContent: 'center' }}
        >
          <T size={14} weight={600} color={c.pr} align="center">
            {mode === 'in' ? 'معندكش حساب؟ أنشئ حساب' : 'عندك حساب؟ سجّل الدخول'}
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
  input: { minHeight: 52, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: 14, fontSize: 16, textAlign: 'right' },
  role: { borderWidth: 1.5, borderRadius: radius.md, padding: 12, gap: 2 },
  main: { minHeight: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
});
