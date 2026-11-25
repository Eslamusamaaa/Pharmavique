// Licensed pharmacies near you, by city. Your position is asked for once, sent in one request and
// dropped: it is not saved here or on the server. The list has no street or coordinates, so this is
// a list of licensed pharmacies in the nearest cities, never a claim about stock or opening hours.
import * as Location from 'expo-location';
import { router } from 'expo-router';
import { ArrowRightIcon, MapPinIcon, PhoneIcon } from '@/components/icons';
import { useEffect, useState } from 'react';
import { Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import {
  arabicPharmacyError,
  getCities,
  getCityPharmacies,
  getNearby,
  mapsSearchUrl,
  type CityChoice,
  type CityPharmacies,
  type Nearby,
  type Pharmacy,
} from '@/api/pharmacies';
import { Card, DisclaimerBar, H2, Loading, Pill, PrimaryButton, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

const NOTE =
  'هذي صيدليات مرخّصة من قائمة الهيئة، مجمّعة حسب المدينة. القائمة ما فيها شارع ولا إحداثيات، فالمسافة لوسط المدينة وليست للصيدلية. وجودها في القائمة لا يعني أن عندها الدواء أو أنها مفتوحة الحين: اتصل قبل ما تروح.';

type Mode = 'start' | 'nearby' | 'city';

export default function Pharmacies() {
  const { c } = useTheme();
  const [mode, setMode] = useState<Mode>('start');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nearby, setNearby] = useState<Nearby | null>(null);
  const [cities, setCities] = useState<CityChoice[]>([]);
  const [picked, setPicked] = useState<{ city: string; results: Pharmacy[]; total: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getCities(controller.signal)
      .then((r) => setCities(r.cities))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const useMyLocation = async () => {
    setError(null);
    setLoading(true);
    try {
      const permission = await Location.requestForegroundPermissionsAsync();
      if (permission.status !== 'granted') {
        setError('ما فيه إذن للموقع. تقدر تختار مدينتك من القائمة تحت.');
        return;
      }
      const here = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      // the position lives only in this call: it is sent once and not stored anywhere
      setNearby(await getNearby(here.coords.latitude, here.coords.longitude));
      setMode('nearby');
    } catch (e) {
      setError(arabicPharmacyError(e));
    } finally {
      setLoading(false);
    }
  };

  const chooseCity = async (city: CityChoice) => {
    setError(null);
    setLoading(true);
    try {
      const r = await getCityPharmacies(city.city_key);
      setPicked({ city: city.city, results: r.results, total: r.total });
      setMode('city');
    } catch (e) {
      setError(arabicPharmacyError(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView edges={['top']} style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={styles.topBar}>
        <Pressable
          onPress={() => (mode !== 'start' ? setMode('start') : router.canGoBack() ? router.back() : router.replace('/'))}
          style={styles.iconBtn}
          accessibilityLabel="رجوع"
        >
          <ArrowRightIcon size={24} color={c.ink} />
        </Pressable>
        <T size={17} weight={700} style={{ flex: 1 }}>
          صيدليات قريبة
        </T>
      </View>
      <DisclaimerBar />
      <ScrollView contentContainerStyle={styles.content}>
        {error ? (
          <T size={14} color={c.rd} align="center">
            {error}
          </T>
        ) : null}
        {loading ? <Loading /> : null}

        {mode === 'start' ? (
          <>
            <PrimaryButton label="استخدم موقعي" icon={<MapPinIcon size={20} color={c.prt} />} onPress={useMyLocation} />
            <T size={13} color={c.ink2}>
              موقعك يُرسل مرة واحدة عشان نعرف أقرب المدن، ولا يُخزَّن في التطبيق ولا على السيرفر.
            </T>
            <H2>أو اختر مدينتك</H2>
            <View style={styles.chips}>
              {cities.map((city) => (
                <Pressable
                  key={city.city_key}
                  onPress={() => chooseCity(city)}
                  style={[styles.chip, { borderColor: c.pr }]}
                  accessibilityRole="button"
                >
                  <T size={14} latin>
                    {city.city} ({city.pharmacies})
                  </T>
                </Pressable>
              ))}
            </View>
          </>
        ) : null}

        {mode === 'nearby' && nearby ? (
          <NearbyView data={nearby} onRetry={() => setMode('start')} />
        ) : null}

        {mode === 'city' && picked ? (
          <View style={{ gap: 10 }}>
            <H2>
              {picked.city} · {picked.total}
            </H2>
            {picked.results.map((p) => (
              <PharmacyCard key={`${p.name}-${p.address}`} p={p} />
            ))}
          </View>
        ) : null}

        <T size={12.5} color={c.ink2}>
          {NOTE}
        </T>
      </ScrollView>
    </SafeAreaView>
  );
}

function NearbyView({ data, onRetry }: { data: Nearby; onRetry: () => void }) {
  const { c } = useTheme();
  if (data.cities.length === 0) {
    return (
      <View style={{ gap: 10 }}>
        <T weight={700}>ما فيه مدينة فيها صيدليات ضمن {data.radius_km} كم منك.</T>
        {data.nearest_outside ? (
          <T size={14}>
            أقرب مدينة في القائمة: {data.nearest_outside.city} (حوالي {data.nearest_outside.distance_km} كم).
          </T>
        ) : null}
        <PrimaryButton label="اختر مدينة" outline onPress={onRetry} />
      </View>
    );
  }
  return (
    <View style={{ gap: 14 }}>
      {data.cities.map((city) => (
        <CityBlock key={city.city_key} city={city} />
      ))}
      {data.pharmacies_without_a_city > 0 ? (
        <T size={12.5} color={c.ink2}>
          {data.pharmacies_without_a_city} صيدلية في القائمة عنوانها بدون مدينة، فهي غير معروضة هنا.
        </T>
      ) : null}
    </View>
  );
}

function CityBlock({ city }: { city: CityPharmacies }) {
  return (
    <View style={{ gap: 8 }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <H2>{city.city}</H2>
        {city.distance_km !== null ? <Pill label={`حوالي ${city.distance_km} كم لوسط المدينة`} /> : null}
      </Row>
      {city.pharmacies.map((p) => (
        <PharmacyCard key={`${p.name}-${p.address}`} p={p} />
      ))}
      {city.total > city.shown ? (
        <T size={13}>وفيه {city.total - city.shown} صيدلية ثانية في {city.city}.</T>
      ) : null}
    </View>
  );
}

function PharmacyCard({ p }: { p: Pharmacy }) {
  const { c } = useTheme();
  return (
    <Card style={{ gap: 6 }}>
      <T weight={700} latin align="left">
        {p.name}
      </T>
      <T size={13} color={c.ink2} latin align="left">
        {p.address}
      </T>
      <Row gap={8}>
        {p.phone ? (
          <Pressable
            onPress={() => Linking.openURL(`tel:${p.phone}`)}
            style={[styles.action, { borderColor: c.pr }]}
            accessibilityRole="button"
            accessibilityLabel={`اتصل بـ ${p.name}`}
          >
            <PhoneIcon size={16} color={c.pr} />
            <T size={13} weight={600} color={c.pr}>
              اتصل
            </T>
          </Pressable>
        ) : null}
        <Pressable
          onPress={() => Linking.openURL(mapsSearchUrl(p))}
          style={[styles.action, { borderColor: c.pr }]}
          accessibilityRole="button"
          accessibilityLabel={`ابحث عن ${p.name} في الخرائط`}
        >
          <MapPinIcon size={16} color={c.pr} />
          <T size={13} weight={600} color={c.pr}>
            ابحث في الخرائط
          </T>
        </Pressable>
      </Row>
    </Card>
  );
}

const styles = StyleSheet.create({
  topBar: { height: 52, flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 8 },
  iconBtn: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 16, gap: 14, paddingBottom: 80 },
  chips: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  chip: { minHeight: 40, paddingHorizontal: 14, borderRadius: radius.pill, borderWidth: 1.5, justifyContent: 'center' },
  action: {
    minHeight: 40,
    paddingHorizontal: 12,
    borderRadius: radius.md,
    borderWidth: 1.5,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 6,
  },
});
