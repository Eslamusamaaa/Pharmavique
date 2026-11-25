"""The emails identity sends. Plain text, Arabic first and English below; no health information."""

from pharmavique.shared_kernel.email import EmailMessage
from pharmavique.shared_kernel.principal import Role

_ROLE_AR = {Role.PHARMACIST: "صيدلي", Role.COMPANY: "شركة"}
_ROLE_EN = {Role.PHARMACIST: "pharmacist", Role.COMPANY: "company"}


def verification_email(to: str, code: str, minutes: int) -> EmailMessage:
    text = (
        f"رمز التأكيد في فارماڤيك: {code}\n"
        f"الرمز صالح لمدة {minutes} دقائق. إذا ما أنت اللي طلبته تجاهل هذه الرسالة، وما أحد يقدر "
        "يدخل حسابك بدون الرمز.\n\n"
        f"Your Pharmavique verification code: {code}\n"
        f"It is valid for {minutes} minutes. If you did not ask for it, ignore this email: nobody "
        "can use your account without the code.\n"
    )
    return EmailMessage(to=to, subject=f"{code} رمز التأكيد · Pharmavique code", text=text)


def role_review_email(to: str, role: Role, approved: bool, note: str | None) -> EmailMessage:
    """An operator verified or rejected a pharmacist or company account (ADR-020)."""
    ar, en = _ROLE_AR.get(role, "مهني"), _ROLE_EN.get(role, "professional")
    if approved:
        text = (
            f"تم توثيق حسابك كحساب {ar} في فارماڤيك، والحين تظهر علامة «موثّق» في حسابك.\n\n"
            f"Your Pharmavique {en} account has been verified; it now shows the verified badge.\n"
        )
        return EmailMessage(to=to, subject="تم توثيق حسابك · Account verified", text=text)
    reason_ar = f"السبب: {note}\n" if note else ""
    reason_en = f"Reason: {note}\n" if note else ""
    text = (
        f"ما قدرنا نوثّق حسابك كحساب {ar} في فارماڤيك.\n{reason_ar}"
        "تقدر تكمل تستخدم التطبيق عادي، بس بدون علامة «موثّق».\n\n"
        f"We could not verify your Pharmavique {en} account.\n{reason_en}"
        "You can keep using the app as before, without the verified badge.\n"
    )
    return EmailMessage(to=to, subject="ما تم توثيق حسابك · Account not verified", text=text)
