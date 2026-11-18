import { router } from 'expo-router';
import { useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { Body, Card, Chip, Disclaimer, SearchBox, Title } from '@/components/ui';

const SAMPLES = ['بنادول اكسترا', 'panadol', 'اوجمنتين', 'نيكسيوم', 'concor'];

function openSearch(q: string) {
  const query = q.trim();
  if (query) router.push({ pathname: '/search', params: { q: query } });
}

export default function Home() {
  const [text, setText] = useState('');
  return (
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <Title>ابحث عن أي دواء مسجل في السعودية</Title>
      <Body muted>بالاسم التجاري أو المادة الفعالة، بالعربي أو الإنجليزي، حتى لو فيه غلطة إملائية.</Body>
      <SearchBox value={text} onChangeText={setText} onSubmitEditing={() => openSearch(text)} />
      <View style={styles.chips}>
        {SAMPLES.map((s) => (
          <Chip key={s} label={s} onPress={() => openSearch(s)} />
        ))}
      </View>
      <Card>
        <Title>مصدر البيانات</Title>
        <Body muted>
          سجل الأدوية الرسمي للهيئة العامة للغذاء والدواء (SFDA). كل معلومة معروضة بمصدرها وتاريخ جلبها.
        </Body>
      </Card>
      <Disclaimer />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: { padding: 16, gap: 14 },
  chips: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
});
