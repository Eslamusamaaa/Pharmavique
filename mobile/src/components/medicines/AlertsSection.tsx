// Changes the registry made to MY medicines only (a price, a withdrawal, a return to the list).
import { router } from 'expo-router';
import { BellIcon } from 'phosphor-react-native';
import { Pressable, View } from 'react-native';

import { displayName } from '@/api/client';
import { markAlertsRead, type AlertItem, type Alerts } from '@/api/me';
import { Card, H2, Row, T } from '@/components/ui';
import { useTheme } from '@/theme';

const KIND_AR: Record<AlertItem['kind'], string> = {
  price_changed: 'تغيّر السعر',
  withdrawn: 'انسحب من السجل',
  relisted: 'رجع للسجل',
};

function detail(a: AlertItem): string {
  if (a.kind === 'price_changed') {
    const { old_price: from, new_price: to } = a.details;
    if (from && to) return `${KIND_AR[a.kind]}: من ${from} إلى ${to}`;
  }
  return KIND_AR[a.kind];
}

export function AlertsSection({ alerts, onChanged }: { alerts: Alerts | null; onChanged: () => void }) {
  const { c } = useTheme();
  return (
    <View style={{ gap: 10 }}>
      <Row style={{ justifyContent: 'space-between' }}>
        <H2>تنبيهات أدويتي {alerts && alerts.unread ? `(${alerts.unread})` : ''}</H2>
        {alerts && alerts.unread ? (
          <Pressable onPress={() => markAlertsRead().then(onChanged).catch(() => undefined)}>
            <T size={13} weight={600} color={c.pr}>
              اعتبرها كلها مقروءة
            </T>
          </Pressable>
        ) : null}
      </Row>
      {alerts && alerts.items.length > 0 ? (
        alerts.items.map((a) => (
          <Pressable
            key={a.id}
            onPress={() => {
              if (!a.read) markAlertsRead(a.id).catch(() => undefined);
              router.push({ pathname: '/drug/[register]', params: { register: a.register_number } });
            }}
          >
            <Card style={{ gap: 4, opacity: a.read ? 0.6 : 1 }}>
              <Row gap={8}>
                <BellIcon size={18} color={c.pr} weight={a.read ? 'regular' : 'fill'} />
                <T weight={700} style={{ flex: 1 }}>
                  {a.product ? displayName(a.product) : a.register_number}
                </T>
              </Row>
              <T size={14}>{detail(a)}</T>
              <T size={12} color={c.ink2}>
                {new Date(a.occurred_at).toLocaleDateString('ar-EG')}
              </T>
            </Card>
          </Pressable>
        ))
      ) : (
        <T size={14} color={c.ink2}>
          ما فيه تنبيهات. توصلك هنا فقط إذا تغيّر سعر دواء من أدويتك أو انسحب من السجل.
        </T>
      )}
    </View>
  );
}
