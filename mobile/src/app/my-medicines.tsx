// "My medicines" for the patient: the list stays on this device and is checked automatically.
import { InteractionBasket } from '@/components/InteractionBasket';

export default function MyMedicines() {
  return (
    <InteractionBasket
      title="أدويتي"
      intro="أضف الأدوية التي تستخدمها، وسنعرض لك التداخلات المسجّلة بينها. القائمة محفوظة على جهازك فقط."
      persist
    />
  );
}
