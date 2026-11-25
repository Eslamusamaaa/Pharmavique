// The assistant, scans and voice need an account while the server's `login_for_ai` feature is on
// (owner's decision, 2026-11-25). A guest sees why and a sign-in button; after signing in, the
// sign-in screen goes back here and the screen itself appears.
import { router } from 'expo-router';
import { useEffect, useState, type ReactNode } from 'react';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { getFeatures } from '@/api/me';
import { Loading, Message, PrimaryButton } from '@/components/ui';
import { useAccount } from '@/state/auth';
import { useTheme } from '@/theme';

export function SignInGate({ what, children }: { what: string; children: ReactNode }) {
  const { c } = useTheme();
  const { account } = useAccount();
  const [needed, setNeeded] = useState<boolean | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    getFeatures(controller.signal).then((f) => setNeeded(f.login_for_ai));
    return () => controller.abort();
  }, []);

  if (account === undefined || (account === null && needed === undefined)) return <Loading />;
  if (account || !needed) return <>{children}</>;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: c.bg }}>
      <Message
        title="سجّل دخولك أول"
        detail={`عشان تستخدم ${what} لازم تسجّل دخولك. بعدها ترجع لنفس المكان.`}
        action={
          <View style={{ gap: 10, alignSelf: 'stretch', paddingHorizontal: 24 }}>
            <PrimaryButton label="تسجيل الدخول" onPress={() => router.push('/sign-in')} />
            <PrimaryButton
              label="رجوع"
              outline
              onPress={() => (router.canGoBack() ? router.back() : router.navigate('/'))}
            />
          </View>
        }
      />
    </SafeAreaView>
  );
}
