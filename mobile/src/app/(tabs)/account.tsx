// E · Account. Sign-in and roles come with the identity context; for now the role is "patient".
import { UserCircleIcon } from 'phosphor-react-native';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DisclaimerBar, T } from '@/components/ui';
import { useTheme } from '@/theme';

export default function Account() {
  const { c } = useTheme();
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
          مريض
        </T>
        <T size={15} color={c.ink2} align="center">
          قيد البناء: تسجيل الدخول وتغيير الدور (مريض، صيدلي) وقائمة أدويتي.
        </T>
      </View>
    </SafeAreaView>
  );
}
