// E · Account. Sign-in comes with the identity context; for now the role is chosen on this device.
import { router } from 'expo-router';
import { UserCircleIcon } from 'phosphor-react-native';
import { Pressable, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DisclaimerBar, T } from '@/components/ui';
import { roleInfo, useRole } from '@/state/role';
import { radius, useTheme } from '@/theme';

export default function Account() {
  const { c } = useTheme();
  const { role } = useRole();
  const current = roleInfo(role ?? 'patient');
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
        <T size={20} weight={700} align="center">
          {current.label}
        </T>
        <T size={15} color={c.ink2} align="center">
          {current.hint}
        </T>
        <Pressable
          onPress={() => router.push('/role')}
          style={{ marginTop: 8, minHeight: 48, paddingHorizontal: 24, borderRadius: radius.md, borderWidth: 1.5, borderColor: c.pr, justifyContent: 'center' }}
          accessibilityRole="button"
        >
          <T weight={600} color={c.pr}>
            غيّر الدور
          </T>
        </Pressable>
        <T size={13} color={c.ink2} align="center">
          قيد البناء: تسجيل الدخول وقائمة أدويتي.
        </T>
      </View>
    </SafeAreaView>
  );
}
