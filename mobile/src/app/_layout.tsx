import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';

import { colors } from '@/theme';

export default function RootLayout() {
  return (
    <>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.primary,
          headerTitleStyle: { color: colors.ink, fontWeight: '700' },
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        <Stack.Screen name="index" options={{ title: 'فارمافيك' }} />
        <Stack.Screen name="search" options={{ title: 'البحث عن دواء' }} />
        <Stack.Screen name="drug/[register]" options={{ title: 'بيانات الدواء' }} />
      </Stack>
    </>
  );
}
