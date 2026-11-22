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

import { useTheme } from '@/theme';

// On the website the app keeps the phone's width, centred, so it looks the same on a computer.
const webColumn = (backgroundColor: string) =>
  ({ flex: 1, width: '100%', maxWidth: 480, alignSelf: 'center', backgroundColor }) as const;

export default function RootLayout() {
  const { c, isDark } = useTheme();
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
  if (!loaded) return <View style={{ flex: 1, backgroundColor: c.bg }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style={isDark ? 'light' : 'dark'} />
      <View style={Platform.OS === 'web' ? webColumn(c.bg) : { flex: 1 }}>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: c.bg } }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="role" />
        <Stack.Screen name="sign-in" />
        <Stack.Screen name="verify-email" />
        <Stack.Screen name="drug/[register]" />
        <Stack.Screen name="compare" />
        <Stack.Screen name="assistant" />
        <Stack.Screen name="interactions" />
        <Stack.Screen name="my-medicines" />
        <Stack.Screen name="my-list" />
        <Stack.Screen name="company" />
        <Stack.Screen name="pharmacies" />
        <Stack.Screen name="shelf" />
        <Stack.Screen name="operator" />
        <Stack.Screen name="voice" options={{ presentation: 'modal' }} />
      </Stack>
      </View>
    </SafeAreaProvider>
  );
}
