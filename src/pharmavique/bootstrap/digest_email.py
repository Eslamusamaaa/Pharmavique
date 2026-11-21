"""The email that tells someone what changed for their saved medicines.

It states what the registry says changed (a price, a withdrawal, a relisting) and nothing about what
to do. Arabic first, English below. It carries no allergy, no list of medicines beyond the ones the
alerts are about, and an unsubscribe link.
"""

from collections.abc import Mapping, Sequence

from pharmavique.shared_kernel.email import EmailMessage
from pharmavique.watchlist.domain.model import Alert, AlertKind

MAX_LINES = 20

_AR = {
    AlertKind.WITHDRAWN: "اتسحب من سجل الهيئة",
    AlertKind.RELISTED: "رجع لسجل الهيئة",
}
_EN = {
    AlertKind.WITHDRAWN: "was withdrawn from the SFDA registry",
    AlertKind.RELISTED: "is listed in the SFDA registry again",
}


def _price(alert: Alert) -> tuple[str, str] | None:
    old, new = alert.details.get("old_price"), alert.details.get("new_price")
    if not old or not new:
        return None
    currency = alert.details.get("currency_code") or ""
    return f"{old} → {new} {currency}".strip(), alert.details.get("currency_basis") or ""


def _line(alert: Alert, name: str) -> tuple[str, str]:
    if alert.kind is AlertKind.PRICE_CHANGED:
        price = _price(alert)
        change = price[0] if price else ""
        basis = " (العملة افتراض مننا)" if price and price[1] == "owner_assumption" else ""
        basis_en = " (currency assumed by us)" if price and price[1] == "owner_assumption" else ""
        return (f"{name}: تغيّر السعر {change}{basis}", f"{name}: price changed {change}{basis_en}")
    return f"{name}: {_AR[alert.kind]}", f"{name} {_EN[alert.kind]}"


def build_digest(
    to: str,
    alerts: Sequence[Alert],
    names: Mapping[str, str],
    unsubscribe_url: str | None,
) -> EmailMessage:
    shown = list(alerts)[:MAX_LINES]
    more = len(alerts) - len(shown)
    ar_lines, en_lines = [], []
    for alert in shown:
        ar, en = _line(alert, names.get(alert.register_number, alert.register_number))
        ar_lines.append(f"- {ar}")
        en_lines.append(f"- {en}")
    if more > 0:
        ar_lines.append(f"- وفي {more} تنبيه تاني في التطبيق")
        en_lines.append(f"- and {more} more in the app")
    footer_ar = "ده تحديث من سجل الهيئة مش نصيحة طبية. اسأل الصيدلي أو الدكتور عن أي دواء بتاخده."
    footer_en = (
        "This is an update from the SFDA registry, not medical advice. "
        "Ask your pharmacist or doctor."
    )
    stop_ar = (
        f"لإيقاف هذه الرسائل: {unsubscribe_url}"
        if unsubscribe_url
        else "لإيقاف هذه الرسائل: حسابي ← التنبيهات بالإيميل في التطبيق."
    )
    stop_en = (
        f"To stop these emails: {unsubscribe_url}"
        if unsubscribe_url
        else "To stop these emails: Account > email notifications in the app."
    )
    text = (
        "تنبيهات على أدويتك المحفوظة في فارماڤيك:\n"
        + "\n".join(ar_lines)
        + f"\n\n{footer_ar}\n{stop_ar}\n\n"
        + "Updates about your saved medicines on Pharmavique:\n"
        + "\n".join(en_lines)
        + f"\n\n{footer_en}\n{stop_en}\n"
    )
    count = len(alerts)
    return EmailMessage(
        to=to,
        subject=f"{count} تنبيه على أدويتك · {count} alert(s) on your medicines",
        text=text,
        unsubscribe_url=unsubscribe_url,
    )
