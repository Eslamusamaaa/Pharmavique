// B6 · Box scan. The camera and the reading model (VLM) are the next build step; until then this
// screen says so plainly instead of pretending to work.
import { ScanIcon } from 'phosphor-react-native';
import { View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DisclaimerBar, T } from '@/components/ui';
import { useTheme } from '@/theme';

export default function Scan() {
  const { c } = useTheme();
  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={{ height: 52, justifyContent: 'center', paddingHorizontal: 16 }}>
        <T size={17} weight={700}>
          المسح الضوئي
        </T>
      </View>
      <DisclaimerBar />
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 }}>
        <ScanIcon size={64} color={c.pr} />
        <T size={20} weight={700} align="center">
          مسح علبة الدواء والروشتة
        </T>
        <T size={15} color={c.ink2} align="center">
          قيد البناء: هنا هتصوّر العلبة أو الروشتة، والنظام يقرا الاسم ويطابقه بسجل الهيئة.
        </T>
      </View>
    </SafeAreaView>
  );
}
