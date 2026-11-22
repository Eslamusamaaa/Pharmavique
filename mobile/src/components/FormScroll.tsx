// A scrolling form that stays usable while the keyboard is open. The content gets as much room under
// it as the keyboard takes, so the last button can always be scrolled into view, and dragging the form
// closes the keyboard (a number pad has no "done" key on iPhone). Taps on buttons still work with the
// keyboard open.
import { useEffect, useState, type ReactNode } from 'react';
import { Keyboard, Platform, ScrollView, type StyleProp, type ViewStyle } from 'react-native';

const SHOW = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
const HIDE = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

export function FormScroll({ children, contentStyle }: { children: ReactNode; contentStyle?: StyleProp<ViewStyle> }) {
  const [keyboard, setKeyboard] = useState(0);

  useEffect(() => {
    const shown = Keyboard.addListener(SHOW, (e) => setKeyboard(e.endCoordinates.height));
    const hidden = Keyboard.addListener(HIDE, () => setKeyboard(0));
    return () => {
      shown.remove();
      hidden.remove();
    };
  }, []);

  return (
    <ScrollView
      contentContainerStyle={[contentStyle, { paddingBottom: keyboard + 32 }]}
      keyboardShouldPersistTaps="handled"
      keyboardDismissMode={Platform.OS === 'ios' ? 'interactive' : 'on-drag'}
    >
      {children}
    </ScrollView>
  );
}
