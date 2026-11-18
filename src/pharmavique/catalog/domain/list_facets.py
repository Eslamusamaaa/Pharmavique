"""Clean values to filter list rows by.

The site spells one thing several ways ("Generic(Multisource) Drug", "Generic (Multisource) Drug",
"Generic", "Generic Drug") and sometimes shifts a row by a column. The raw cells are always kept;
these facets sit beside them. A value the rules do not know is kept as a slug of what the site
wrote, never guessed, and a row that looks shifted is flagged, not repaired.
"""

import re
from collections.abc import Mapping

_DRUG_TYPES = {
    "generic(multisource) drug": "generic",
    "generic (multisource) drug": "generic",
    "generic": "generic",
    "generic drug": "generic",
    "new drug": "new_drug",
    "nce": "nce",
    "biological drug": "biological",
    "biological": "biological",
    "biosimilar": "biosimilar",
}
_REQUEST_TYPES = {"new registration": "new_registration", "registration": "registration"}
_COMPANY_STATUS = {
    "مسجلة": "registered",
    "خط انتاج": "production_line",
    "معلقة": "suspended",
    "ملغية": "cancelled",
    "تحت التسجيل": "under_registration",
}
_COMPANY_TYPE = {"بشرية": "human", "عشبية": "herbal", "بيطرية": "veterinary"}
_AVAILABILITY = {"غير متوفر": "unavailable", "تم الحل": "resolved"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _approvals(cells: Mapping[str, str]) -> dict[str, str]:
    facets: dict[str, str] = {}
    request = " ".join(cells.get("Request Type", "").split())
    form = " ".join(cells.get("Dosage Form", "").split())
    if request.lower() in _REQUEST_TYPES:
        facets["request_type"] = _REQUEST_TYPES[request.lower()]
    elif request and form in ("", "-"):
        facets["row_shifted"] = "true"  # a dosage form sits in the request-type column
    drug_type = " ".join(cells.get("Drug Type", "").split())
    if drug_type:
        facets["drug_type"] = _DRUG_TYPES.get(drug_type.lower(), _slug(drug_type))
    if form and form != "-":
        facets["dosage_form"] = form.lower()
    return facets


def facets_for(list_name: str, cells: Mapping[str, str]) -> dict[str, str]:
    if list_name == "drug-approvals":
        return _approvals(cells)
    if list_name == "drug-companies":
        facets: dict[str, str] = {}
        status = _COMPANY_STATUS.get(cells.get("Company status", "").strip())
        kind = _COMPANY_TYPE.get(cells.get("Drug Type", "").strip())
        if status:
            facets["status"] = status
        if kind:
            facets["drug_type"] = kind
        return facets
    if list_name in ("drug-shortage", "drug-shortage-resolved"):
        value = _AVAILABILITY.get(cells.get("Availability Status", "").strip())
        return {"availability": value} if value else {}
    return {}
