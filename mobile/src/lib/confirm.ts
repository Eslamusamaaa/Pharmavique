// A yes/no question that works on the phone and on the website: React Native's Alert does nothing
// in a browser, so there the browser's own confirm box is used.
import { Alert, Platform } from 'react-native';

export function confirmAction(title: string, message: string, confirmLabel: string, onConfirm: () => void) {
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined' && window.confirm(`${title}\n\n${message}`)) onConfirm();
    return;
  }
  Alert.alert(title, message, [
    { text: 'إلغاء', style: 'cancel' },
    { text: confirmLabel, style: 'destructive', onPress: onConfirm },
  ]);
}
