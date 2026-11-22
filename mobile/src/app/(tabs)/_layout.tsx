import { Redirect } from 'expo-router';
import { Tabs } from 'expo-router/js-tabs';
import { View } from 'react-native';

import { TabBar } from '@/components/TabBar';
import { useRole } from '@/state/role';
import { useTheme } from '@/theme';

export default function TabsLayout() {
  const { role, ready } = useRole();
  const { c } = useTheme();
  if (!ready) return <View style={{ flex: 1, backgroundColor: c.bg }} />;
  if (!role) return <Redirect href="/role" />;
  return (
    <Tabs
      tabBar={(props) => <TabBar {...props} />}
      // B4: the tab bar hides while the keyboard is open so nothing fixed fights it
      screenOptions={{ headerShown: false, tabBarHideOnKeyboard: true }}
    >
      <Tabs.Screen name="index" />
      <Tabs.Screen name="search" />
      <Tabs.Screen name="scan" />
      <Tabs.Screen name="medicines" />
      <Tabs.Screen name="account" />
    </Tabs>
  );
}
