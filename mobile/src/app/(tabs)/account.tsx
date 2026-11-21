// E · Account: the signed-in account, or a way to sign in. Search and the assistant need no account.
import { router } from 'expo-router';
import { UserCircleIcon } from 'phosphor-react-native';
import { useState } from 'react';
import { Alert, Pressable, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, deleteAccount, signOut } from '@/api/auth';
import { DisclaimerBar, T } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { roleInfo, useRole } from '@/state/role';
import { radius, useTheme } from '@/theme';

const ROLE_LABEL: Record<string, string> = {
  patient: 'مريض',
  pharmacist: 'صيدلي',
  company: 'شركة أو مخزن أدوية',
  operator: 'مشغّل المنصة',
};

export default function Account() {
  const { c } = useTheme();
  const { role } = useRole();
  const { account } = useAccount();
  const [message, setMessage] = useState<string | null>(null);
  const current = roleInfo(role ?? 'patient');

  const confirmDelete = () =>
    Alert.alert('حذف الحساب', 'هيتمسح الحساب وكل اللي محفوظ فيه. مفيش رجوع.', [
      { text: 'إلغاء', style: 'cancel' },
      {
        text: 'احذف',
        style: 'destructive',
        onPress: () => deleteAccount().catch((e: unknown) => setMessage(arabicAuthError(e))),
      },
    ]);

  const outline = {
    minHeight: 48,
    paddingHorizontal: 24,
    borderRadius: radius.md,
    borderWidth: 1.5,
    justifyContent: 'center' as const,
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={{ height: 52, justifyContent: 'center', paddingHorizontal: 16 }}>
        <T size={17} weight={700}>
          حسابي
        </T>
      </View>
      <DisclaimerBar />
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 }}>
        <UserCircleIcon size={64} color={c.pr} />
        {account ? (
          <>
            <T size={18} weight={700} align="center" latin>
              {account.email}
            </T>
            <T size={15} color={c.ink2} align="center">
              {ROLE_LABEL[account.role] ?? account.role}
            </T>
            <Pressable
              onPress={() => router.push('/my-list')}
              style={[outline, { borderColor: c.pr, backgroundColor: c.pr, marginTop: 8 }]}
              accessibilityRole="button"
            >
              <T weight={700} color={c.prt}>
                قائمتي وتنبيهاتي
              </T>
            </Pressable>
            {account.role === 'company' || account.role === 'operator' ? (
              <Pressable
                onPress={() => router.push('/company')}
                style={[outline, { borderColor: c.pr }]}
                accessibilityRole="button"
              >
                <T weight={600} color={c.pr}>
                  شاشة الشركات
                </T>
              </Pressable>
            ) : null}
            {account.role === 'pharmacist' || account.role === 'operator' ? (
              <Pressable
                onPress={() => router.push('/shelf')}
                style={[outline, { borderColor: c.pr }]}
                accessibilityRole="button"
              >
                <T weight={600} color={c.pr}>
                  مسح الرف
                </T>
              </Pressable>
            ) : null}
            {account.role === 'operator' ? (
              <Pressable
                onPress={() => router.push('/operator')}
                style={[outline, { borderColor: c.pr }]}
                accessibilityRole="button"
              >
                <T weight={600} color={c.pr}>
                  جودة البيانات
                </T>
              </Pressable>
            ) : null}
            <Pressable onPress={() => signOut()} style={[outline, { borderColor: c.pr }]} accessibilityRole="button">
              <T weight={600} color={c.pr}>
                تسجيل الخروج
              </T>
            </Pressable>
            <Pressable onPress={confirmDelete} style={[outline, { borderColor: c.rd }]} accessibilityRole="button">
              <T weight={600} color={c.rd}>
                حذف الحساب
              </T>
            </Pressable>
          </>
        ) : (
          <>
            <T size={20} weight={700} align="center">
              {current.label}
            </T>
            <T size={15} color={c.ink2} align="center">
              {current.hint}
            </T>
            <Pressable
              onPress={() => router.push('/sign-in')}
              style={[outline, { borderColor: c.pr, backgroundColor: c.pr, marginTop: 8 }]}
              accessibilityRole="button"
            >
              <T weight={700} color={c.prt}>
                تسجيل الدخول أو إنشاء حساب
              </T>
            </Pressable>
            <Pressable onPress={() => router.push('/role')} style={[outline, { borderColor: c.pr }]} accessibilityRole="button">
              <T weight={600} color={c.pr}>
                غيّر الدور
              </T>
            </Pressable>
            <T size={13} color={c.ink2} align="center">
              البحث والمساعد شغالين من غير حساب. الحساب للأدوية المحفوظة والتنبيهات.
            </T>
          </>
        )}
        {message ? (
          <T size={14} color={c.rd} align="center">
            {message}
          </T>
        ) : null}
      </View>
    </SafeAreaView>
  );
}
