// The product picture from the API, or a quiet placeholder when the drug has none.
import { Image } from 'expo-image';
import { PillIcon } from 'phosphor-react-native';
import { useState } from 'react';
import { View } from 'react-native';

import { pictureUrl } from '@/api/client';
import { radius, useTheme } from '@/theme';

export function DrugPicture({ register, size = 72 }: { register: string; size?: number }) {
  const { c } = useTheme();
  const [failed, setFailed] = useState(false);
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: radius.md,
        backgroundColor: c.prs,
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
      }}
    >
      {failed ? (
        <PillIcon size={size * 0.42} color={c.ink2} />
      ) : (
        <Image
          source={{ uri: pictureUrl(register) }}
          style={{ width: size, height: size }}
          contentFit="contain"
          onError={() => setFailed(true)}
          accessibilityLabel="صورة الدواء"
        />
      )}
    </View>
  );
}
