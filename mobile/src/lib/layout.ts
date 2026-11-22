// One breakpoint decides the layout: a phone (and a narrow window) gets the bottom tab bar and one
// column; a computer gets the side navigation rail and wider, multi-column screens.
import { useWindowDimensions } from 'react-native';

export const WIDE_FROM = 900;

export function useWide(): boolean {
  return useWindowDimensions().width >= WIDE_FROM;
}
