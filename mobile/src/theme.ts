// Design tokens from pharmavique-wireframes (D1 · Design tokens), light and dark.
import { useColorScheme } from 'react-native';

export type Palette = {
  bg: string;
  sf: string;
  ink: string;
  ink2: string;
  ln: string;
  pr: string;
  ac: string;
  prs: string;
  prt: string;
  ok: string;
  oks: string;
  wn: string;
  wns: string;
  rd: string;
  rds: string;
  or: string;
  ors: string;
};

export const light: Palette = {
  bg: '#F5F9F8',
  sf: '#FFFFFF',
  ink: '#0F2427',
  ink2: '#4B6365',
  ln: '#D9E3E3',
  pr: '#0D4450',
  ac: '#1AAAAA',
  prs: '#E4F1F1',
  prt: '#FFFFFF',
  ok: '#17703F',
  oks: '#E2F3E9',
  wn: '#8A5800',
  wns: '#FFF0CC',
  rd: '#B3261E',
  rds: '#FDE7E5',
  or: '#A04600',
  ors: '#FFE8D4',
};

export const dark: Palette = {
  bg: '#0F2427',
  sf: '#173236',
  ink: '#E7F1F1',
  ink2: '#9FB7B8',
  ln: '#2B4649',
  pr: '#3CC8C4',
  ac: '#1AAAAA',
  prs: '#14393C',
  prt: '#0A1B1D',
  ok: '#74D79B',
  oks: '#12301F',
  wn: '#F3C455',
  wns: '#3A2E0B',
  rd: '#FF9D95',
  rds: '#41191A',
  or: '#FFB67F',
  ors: '#3D2312',
};

export function useTheme(): { c: Palette; isDark: boolean } {
  const isDark = useColorScheme() === 'dark';
  return { c: isDark ? dark : light, isDark };
}

// Radius (D1): sm 8, md 12, lg 16, sheet 24, pill 28.
export const radius = { sm: 8, md: 12, lg: 16, sheet: 24, pill: 999 };

// Elevation "card" (D1): 0 1px 2px rgba(18,41,43,.08), 0 4px 12px rgba(18,41,43,.06).
export const cardShadow = {
  shadowColor: '#12292B',
  shadowOpacity: 0.08,
  shadowRadius: 8,
  shadowOffset: { width: 0, height: 3 },
  elevation: 2,
};

// Type (D1): IBM Plex Sans Arabic for Arabic, Inter for Latin drug names and digits.
export const fonts = {
  ar: {
    400: 'IBMPlexSansArabic_400Regular',
    500: 'IBMPlexSansArabic_500Medium',
    600: 'IBMPlexSansArabic_600SemiBold',
    700: 'IBMPlexSansArabic_700Bold',
  },
  latin: {
    400: 'Inter_400Regular',
    500: 'Inter_500Medium',
    600: 'Inter_600SemiBold',
    700: 'Inter_700Bold',
  },
} as const;

export type Weight = 400 | 500 | 600 | 700;

export const DISCLAIMER =
  'معلومات للاطلاع فقط وليست نصيحة طبية. استشر الصيدلي أو الطبيب قبل أي تغيير في دواء.';
