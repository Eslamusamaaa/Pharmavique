// A drug compared with the medicines I take now (recorded interactions from outside sources).
// It never says to stop or change anything; "nothing found" is never "safe".
import { InfoIcon, WarningIcon } from 'phosphor-react-native';
import { View } from 'react-native';

import type { HistoryCheck } from '@/api/me';
import { Pill, Row, T } from '@/components/ui';
import { radius, useTheme } from '@/theme';

const SEVERITY_AR: Record<string, string> = {
  major: 'شديد',
  moderate: 'متوسط',
  minor: 'بسيط',
  unknown: 'غير محدد',
};

export function HistoryCard({ check }: { check: HistoryCheck }) {
  const { c } = useTheme();
  const hasFindings = check.findings.length > 0;
  return (
    <View
      style={{
        borderWidth: 1.5,
        borderRadius: radius.lg,
        padding: 14,
        gap: 8,
        borderColor: hasFindings ? c.wn : c.ln,
        backgroundColor: c.sf,
      }}
    >
      <Row gap={8}>
        {hasFindings ? <WarningIcon size={20} color={c.wn} weight="fill" /> : <InfoIcon size={20} color={c.ink2} />}
        <T weight={700} style={{ flex: 1 }}>
          {hasFindings ? 'فيه تداخل مسجّل مع أدويتك الحالية' : 'تمت المقارنة بأدويتك الحالية'}
        </T>
      </Row>
      <T size={13} color={c.ink2}>
        قورن مع: {check.compared_with.map((m) => m.name).join('، ')}
      </T>
      {check.findings.map((f) => (
        <View key={`${f.kind}-${f.with_register_number}-${f.ingredients.join('+')}`} style={{ gap: 4 }}>
          <T weight={600}>
            {f.kind === 'duplicate_ingredient' ? 'نفس المادة الفعالة موجودة في دواء ثاني تأخذه' : 'تداخل مسجّل'}: {f.with_name}
          </T>
          <T size={13} latin align="left">
            {f.ingredients.join(' ↔ ')}
          </T>
          {f.severity ? <Pill tone="wn" label={`تصنيف المصدر: ${SEVERITY_AR[f.severity] ?? f.severity}`} /> : null}
          {f.source ? (
            <T size={12} color={c.ink2} latin align="left">
              {f.source}
            </T>
          ) : null}
        </View>
      ))}
      {check.already_taken ? (
        <T size={13} color={c.ink2}>
          هذا الدواء موجود أصلًا في أدويتك الحالية.
        </T>
      ) : null}
      {check.unmatched_ingredients.length > 0 ? (
        <T size={12.5} color={c.ink2}>
          المصدر ما يقدر يحكم على: {check.unmatched_ingredients.join('، ')}. وهذا لا يعني أنه ما فيه تداخل.
        </T>
      ) : null}
      <T size={12.5} color={c.ink2}>
        {check.note}
      </T>
    </View>
  );
}
