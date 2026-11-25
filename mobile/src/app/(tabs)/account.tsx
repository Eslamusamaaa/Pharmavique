// حسابي: who is signed in, the email-alert switch, the tools of my role, sign out and delete.
// Search and the assistant need no account. My medicines and allergies live in the أدويتي tab.
import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { arabicAuthError, deleteAccount, setEmailNotifications, signOut } from '@/api/auth';
import { Group, LinkRow, SwitchRow } from '@/components/AccountParts';
import { CheckCircleIcon } from '@/components/icons';
import { DisclaimerBar, Pill, PrimaryButton, Row, T } from '@/components/ui';
import { confirmAction } from '@/lib/confirm';
import { useAccount } from '@/state/auth';
import { roleInfo, useRole } from '@/state/role';
import { useTheme } from '@/theme';

const ROLE_LABEL: Record<string, string> = {
  patient: 'مريض',
  pharmacist: 'صيدلي',
  company: 'شركة أو مخزن أدوية',
  operator: 'مشغّل المنصة',
};

function Avatar({ letter }: { letter: string }) {
  const { c } = useTheme();
  return (
    <View
      style={{ width: 84, height: 84, borderRadius: 42, backgroundColor: c.pr, alignItems: 'center', justifyContent: 'center' }}
    >
      <T size={34} weight={700} color={c.prt} latin>
        {letter.toUpperCase()}
      </T>
    </View>
  );
}

export default function Account() {
  const { c } = useTheme();
  const { role } = useRole();
  const { account } = useAccount();
  const [message, setMessage] = useState<string | null>(null);
  const current = roleInfo(role ?? 'patient');

  const confirmDelete = () =>
    confirmAction('حذف الحساب', 'بيتم حذف الحساب وكل ما هو محفوظ فيه. ما فيه رجعة.', 'احذف', () => {
      deleteAccount().catch((e: unknown) => setMessage(arabicAuthError(e)));
    });

  const tools: { label: string; hint: string; path: '/company' | '/shelf' | '/operator' }[] = [];
  if (account?.role === 'company' || account?.role === 'operator') {
    tools.push({ label: 'شاشة الشركات', hint: 'خريطة السوق والفجوات والرادار', path: '/company' });
  }
  if (account?.role === 'pharmacist' || account?.role === 'operator') {
    tools.push({ label: 'مسح الرف', hint: 'صوّر رف الصيدلية وأضف أدويته', path: '/shelf' });
  }
  if (account?.role === 'operator') {
    tools.push({ label: 'جودة البيانات', hint: 'حالة التحديث والسجل', path: '/operator' });
  }

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={{ height: 52, justifyContent: 'center', paddingHorizontal: 16 }}>
        <T size={17} weight={700}>
          حسابي
        </T>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={{ padding: 16, gap: 20, alignItems: 'center' }}>
        {account ? (
          <>
            <View style={{ alignItems: 'center', gap: 8, paddingVertical: 8 }}>
              <Avatar letter={account.email.slice(0, 1)} />
              <T size={17} weight={700} align="center" latin>
                {account.email}
              </T>
              <Row gap={6}>
                <Pill label={ROLE_LABEL[account.role] ?? account.role} />
                {account.role_review === 'verified' ? (
                  <Pill tone="ok" label="موثّق" icon={<CheckCircleIcon size={14} color={c.ok} weight="fill" />} />
                ) : account.role_review === 'pending' ? (
                  <Pill tone="wn" label="حسابك تحت المراجعة" />
                ) : account.role_review === 'rejected' ? (
                  <Pill tone="muted" label="ما تم توثيق الحساب" />
                ) : null}
              </Row>
            </View>

            <Group title="الإشعارات">
              <SwitchRow
                label="تنبيهات على الإيميل"
                hint="رسالة واحدة عند تغيّر سعر أو سحب أحد أدويتك المحفوظة فقط. التنبيهات تظل ظاهرة في التطبيق."
                value={account.email_notifications}
                onChange={(on) => setEmailNotifications(on).catch((e: unknown) => setMessage(arabicAuthError(e)))}
              />
            </Group>

            {tools.length > 0 ? (
              <Group title="أدواتي">
                {tools.map((t, i) => (
                  <LinkRow
                    key={t.path}
                    label={t.label}
                    hint={t.hint}
                    onPress={() => router.push(t.path)}
                    last={i === tools.length - 1}
                  />
                ))}
              </Group>
            ) : null}

            <Group title="الحساب">
              <LinkRow label="تسجيل الخروج" onPress={() => signOut()} />
              <LinkRow label="حذف الحساب" danger last onPress={confirmDelete} />
            </Group>
          </>
        ) : (
          <>
            <View style={{ alignItems: 'center', gap: 8, paddingVertical: 8 }}>
              <Avatar letter="؟" />
              <T size={20} weight={700} align="center">
                {current.label}
              </T>
              <T size={15} color={c.ink2} align="center">
                {current.hint}
              </T>
            </View>
            <View style={{ alignSelf: 'stretch', gap: 12 }}>
              <PrimaryButton label="تسجيل الدخول أو إنشاء حساب" onPress={() => router.push('/sign-in')} />
              <PrimaryButton label="غيّر الدور" outline onPress={() => router.push('/role')} />
            </View>
            <T size={13} color={c.ink2} align="center">
              البحث وصفحات الأدوية تشتغل بدون حساب. الحساب للمساعد والتصوير والأدوية المحفوظة والتنبيهات.
            </T>
          </>
        )}
        {message ? (
          <T size={14} color={c.rd} align="center">
            {message}
          </T>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}
