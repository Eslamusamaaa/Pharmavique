"""Trust grades and the catalogue of data sources (owner's decision, 2026-11-25).

Three grades, so that a screen never mixes official Saudi data, an official foreign reference and
research data nobody has verified:

- `official_sa`: read from an official Saudi source (SFDA), shown as published with its fetch date;
- `official_foreign`: an official reference of another country (for example the US label text),
  whose products may differ from the ones registered in Saudi Arabia;
- `unverified`: research or open data that no pharmacist and no authority has checked. A source
  nobody listed here is never promoted: it is `unverified`.

Arabic copy is Saudi dialect. Nothing here is medical advice.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class TrustGrade(StrEnum):
    OFFICIAL_SA = "official_sa"
    OFFICIAL_FOREIGN = "official_foreign"
    UNVERIFIED = "unverified"


GRADE_LABEL_AR: dict[TrustGrade, str] = {
    TrustGrade.OFFICIAL_SA: "رسمي سعودي",
    TrustGrade.OFFICIAL_FOREIGN: "مرجع رسمي أجنبي",
    TrustGrade.UNVERIFIED: "غير موثّق",
}

GRADE_LABEL_EN: dict[TrustGrade, str] = {
    TrustGrade.OFFICIAL_SA: "Official Saudi",
    TrustGrade.OFFICIAL_FOREIGN: "Official foreign reference",
    TrustGrade.UNVERIFIED: "Unverified",
}

GRADE_MEANING_AR: dict[TrustGrade, str] = {
    TrustGrade.OFFICIAL_SA: "بيانات من مصدر رسمي سعودي، نعرضها كما نشرها مع تاريخ جلبها.",
    TrustGrade.OFFICIAL_FOREIGN: (
        "مصدر رسمي من جهة غير سعودية (مثل إدارة الغذاء والدواء الأمريكية). "
        "المنتجات فيه ممكن تختلف عن المسجّلة في السعودية."
    ),
    TrustGrade.UNVERIFIED: (
        "من أبحاث أو بيانات مفتوحة ما راجعها صيدلي ولا جهة رسمية. "
        "اعتبرها معلومة للاطلاع بس، وراجع الصيدلي."
    ),
}


@dataclass(frozen=True, slots=True)
class SourceDef:
    id: str
    name_ar: str
    name_en: str
    grade: TrustGrade
    cadence_ar: str  # how it is refreshed, in words
    used_for_ar: str
    url: str | None = None  # a public page of the source, only where this repository knows one


SOURCES: tuple[SourceDef, ...] = (
    SourceDef(
        "sfda-drugs",
        "سجل الأدوية في هيئة الغذاء والدواء السعودية",
        "SFDA drug registry",
        TrustGrade.OFFICIAL_SA,
        "يومي",
        "بيانات الأدوية والبحث والبدائل والأسعار",
        "https://www.sfda.gov.sa/en/drugs-list",
    ),
    SourceDef(
        "sfda-lists",
        "قوائم هيئة الغذاء والدواء (النواقص والصيدليات وغيرها)",
        "SFDA official lists (shortages, pharmacies, others)",
        TrustGrade.OFFICIAL_SA,
        "يومي لقوائم النواقص، وأسبوعي أو شهري لباقي القوائم",
        "نواقص الأدوية والصيدليات المرخّصة",
        "https://www.sfda.gov.sa/en/lists-categories",
    ),
    SourceDef(
        "sfda-safety-documents",
        "نشرات السلامة من هيئة الغذاء والدواء",
        "SFDA safety notices and circulars",
        TrustGrade.OFFICIAL_SA,
        "يومي (الصفوف الجديدة فقط)",
        "إجابات المساعد المقتبسة من نشرات السلامة",
    ),
    SourceDef(
        "openfda-labels",
        "نصوص النشرات الأمريكية (openFDA وDailyMed)",
        "US drug labels (openFDA, DailyMed)",
        TrustGrade.OFFICIAL_FOREIGN,
        "تنزيل ثابت، ما يتحدّث تلقائيًا",
        "نص التداخلات الدوائية في إجابات المساعد",
        "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm",
    ),
    SourceDef(
        "ddinter-2.0",
        "قاعدة التداخلات DDInter 2.0",
        "DDInter 2.0 drug-interaction database",
        TrustGrade.UNVERIFIED,
        "تنزيل ثابت، ما يتحدّث تلقائيًا",
        "التداخلات بين الأدوية، وهي ناقصة: عدم ظهور تداخل لا يعني أن الجمع آمن",
    ),
    SourceDef(
        "medic",
        "قاعدة موانع الاستعمال MeDIC",
        "MeDIC contraindication database",
        TrustGrade.UNVERIFIED,
        "تنزيل ثابت، ما يتحدّث تلقائيًا",
        "موانع الاستعمال، بعد تصفية الصفوف اللي نصّها ما يذكر الحالة",
    ),
    SourceDef(
        "product-pictures",
        "صور المنتجات",
        "Product pictures",
        TrustGrade.UNVERIFIED,
        "يدوي",
        "صور العلب، بعضها حقيقي وبعضها مولّد وما يمثّل العلبة الفعلية",
    ),
)

SOURCES_BY_ID = {s.id: s for s in SOURCES}


def grade_of_source(source: str | None) -> TrustGrade:
    """The grade of a stored source name; a name nobody listed is never promoted."""
    name = (source or "").strip().lower()
    if name.startswith(("openfda", "dailymed")):
        return TrustGrade.OFFICIAL_FOREIGN
    if name.startswith("sfda"):
        return TrustGrade.OFFICIAL_SA
    return TrustGrade.UNVERIFIED


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def source_key_for_host(host: str) -> str | None:
    """Which catalogue source a document's web host belongs to; None when it is not one of ours."""
    host = host.strip().lower()
    if _host_is(host, "sfda.gov.sa"):
        return "sfda-safety-documents"
    if _host_is(host, "fda.gov") or _host_is(host, "nlm.nih.gov"):
        return "openfda-labels"
    return None


def grade_of_citation(kind: str, source_id: str, url: str | None) -> TrustGrade:
    """The grade of what an assistant citation points at."""
    if kind in {"catalog", "sfda_site"}:
        return TrustGrade.OFFICIAL_SA
    if kind in {"interaction", "contraindication"}:
        parts = source_id.split(":")
        return grade_of_source(parts[1] if len(parts) > 1 else None)
    if kind == "document" and url:
        key = source_key_for_host(urlparse(url).hostname or "")
        return SOURCES_BY_ID[key].grade if key else TrustGrade.UNVERIFIED
    return TrustGrade.UNVERIFIED  # "web" and anything else
