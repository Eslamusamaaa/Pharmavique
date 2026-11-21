// Interaction check for the pharmacist: nothing is saved.
import { InteractionBasket } from '@/components/InteractionBasket';

export default function Interactions() {
  return (
    <InteractionBasket
      title="فحص التداخل بين الأدوية"
      intro="أضف دوائين أو أكثر لترى التداخلات المسجّلة في المصدر بينها والمواد الفعالة المكررة."
      persist={false}
    />
  );
}
