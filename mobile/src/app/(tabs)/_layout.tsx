import { Redirect } from 'expo-router';
import { Tabs } from 'expo-router/js-tabs';
import { View } from 'react-native';

import { TabBar } from '@/components/TabBar';
import { useWide } from '@/lib/layout';
import { useRole } from '@/state/role';
import { useTheme } from '@/theme';

export default function TabsLayout() {
  const { role, ready } = useRole();
  const { c } = useTheme();
  const wide = useWide();
  if (!ready) return <View style={{ flex: 1, backgroundColor: c.bg }} />;
  if (!role) return <Redirect href="/role" />;
  return (
    <Tabs
      tabBar={(props) => <TabBar {...props} />}
      // B4: the tab bar hides while the keyboard is open so nothing fixed fights it
      screenOptions={{
        headerShown: false,
        tabBarHideOnKeyboard: true,
        // the page is right to left, so the navigation rail on the right is `left` in the navigator
        tabBarPosition: wide ? 'left' : 'bottom',
        sceneStyle: { backgroundColor: c.bg },
      }}
    >
      <Tabs.Screen name="index" />
      <Tabs.Screen name="search" />
      <Tabs.Screen name="scan" />
      <Tabs.Screen name="medicines" />
      <Tabs.Screen name="account" />
    </Tabs>
  );
}
