"""The emails identity sends. Plain text, Arabic first and English below; no health information."""

from pharmavique.shared_kernel.email import EmailMessage


def verification_email(to: str, code: str, minutes: int) -> EmailMessage:
    text = (
        f"رمز التأكيد في فارماڤيك: {code}\n"
        f"الرمز صالح لمدة {minutes} دقائق. لو ما أنت اللي طلبته تجاهل هذه الرسالة، ومحدش هيقدر "
        "يدخل حسابك من غير الرمز.\n\n"
        f"Your Pharmavique verification code: {code}\n"
        f"It is valid for {minutes} minutes. If you did not ask for it, ignore this email: nobody "
        "can use your account without the code.\n"
    )
    return EmailMessage(to=to, subject=f"{code} رمز التأكيد · Pharmavique code", text=text)
