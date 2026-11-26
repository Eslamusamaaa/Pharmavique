import {
  IBMPlexSansArabic_400Regular,
  IBMPlexSansArabic_500Medium,
  IBMPlexSansArabic_600SemiBold,
  IBMPlexSansArabic_700Bold,
} from '@expo-google-fonts/ibm-plex-sans-arabic';
import { Inter_400Regular, Inter_500Medium, Inter_600SemiBold, Inter_700Bold, useFonts } from '@expo-google-fonts/inter';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { Platform, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useWide } from '@/lib/layout';
import { useTheme } from '@/theme';

// On the website a phone-sized window fills the screen; a narrow-but-wide window (a tablet held
// upright) keeps a readable column; a computer gets the full shell up to a comfortable width.
const webColumn = (backgroundColor: string, wide: boolean) =>
  ({ flex: 1, width: '100%', maxWidth: wide ? 1360 : 640, alignSelf: 'center', backgroundColor }) as const;

export default function RootLayout() {
  const { c, isDark } = useTheme();
  const wide = useWide();
  const [loaded] = useFonts({
    IBMPlexSansArabic_400Regular,
    IBMPlexSansArabic_500Medium,
    IBMPlexSansArabic_600SemiBold,
    IBMPlexSansArabic_700Bold,
    Inter_400Regular,
    Inter_500Medium,
    Inter_600SemiBold,
    Inter_700Bold,
  });
  // On a computer a pushed screen keeps a readable column instead of stretching across the window.
  const column = (maxWidth: number) => ({
    contentStyle: { backgroundColor: c.bg, width: '100%', maxWidth, alignSelf: 'center' },
  }) as const;
  const page = wide ? column(880) : undefined;
  const dashboard = wide ? column(1100) : undefined;
  if (!loaded) return <View style={{ flex: 1, backgroundColor: c.bg }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <View style={Platform.OS === 'web' ? webColumn(c.bg, wide) : { flex: 1 }}>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="role" options={page} />
        <Stack.Screen name="sign-in" options={page} />
        <Stack.Screen name="verify-email" options={page} />
        <Stack.Screen name="forgot-password" options={page} />
        <Stack.Screen name="drug/[register]" options={page} />
        <Stack.Screen name="compare" options={page} />
        <Stack.Screen name="assistant" options={page} />
        <Stack.Screen name="interactions" options={page} />
        <Stack.Screen name="my-medicines" options={page} />
        <Stack.Screen name="my-list" options={page} />
        <Stack.Screen name="company" options={dashboard} />
        <Stack.Screen name="pharmacies" options={page} />
        <Stack.Screen name="shelf" options={page} />
        <Stack.Screen name="operator" options={dashboard} />
        <Stack.Screen name="shared/[token]" options={page} />
        <Stack.Screen name="voice" options={{ presentation: 'modal' }} />
      </Stack>
      </View>
    </SafeAreaProvider>
  );
}
