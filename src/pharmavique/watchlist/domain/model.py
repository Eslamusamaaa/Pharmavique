"""A person's saved medicines, recorded allergies and the alerts about their medicines.

Allergies are recorded by **active ingredient name**, chosen from the catalog. Matching is by name
only: a medicine whose ingredient is the recorded one, or the same substance with a salt or ester
word added ("amoxicillin" and "amoxicillin trihydrate"). Class allergies (penicillin to amoxicillin)
are not covered because no clinical source is available, and the answer says so.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.text import normalize_text

MAX_MEDICINES = 300
MAX_ALLERGIES = 50
MAX_INGREDIENT_LENGTH = 200


class AlertKind(StrEnum):
    PRICE_CHANGED = "price_changed"
    WITHDRAWN = "withdrawn"
    RELISTED = "relisted"


class MedicineStatus(StrEnum):
    """The person's own record: a medicine they take now, or one they took before."""

    CURRENT = "current"
    PAST = "past"


@dataclass(frozen=True, slots=True)
class SavedMedicine:
    register_number: str
    added_at: datetime
    status: MedicineStatus = MedicineStatus.CURRENT
    status_changed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Allergy:
    ingredient: str  # as the catalog writes it (shown to the person)
    key: str  # normalized, what matching and uniqueness use
    added_at: datetime


@dataclass(frozen=True, slots=True)
class Alert:
    id: UUID
    user_id: UUID
    kind: AlertKind
    register_number: str
    event_id: UUID  # one alert per user and event: re-delivery of an event adds nothing
    occurred_at: datetime
    details: Mapping[str, str | None]
    created_at: datetime
    read_at: datetime | None


@dataclass(frozen=True, slots=True)
class AllergyMatch:
    allergy: str  # the ingredient the person recorded
    ingredient: str  # the medicine's ingredient that matched it


def ingredient_key(name: str) -> str:
    key = normalize_text(name)
    if not key or len(name) > MAX_INGREDIENT_LENGTH:
        raise InvariantViolation("enter the name of an active ingredient")
    return key


def _same_substance(a: str, b: str) -> bool:
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def allergy_matches(
    allergies: Iterable[Allergy], ingredient_names: Iterable[str]
) -> list[AllergyMatch]:
    """Which of a medicine's ingredients match a recorded allergy, by name."""
    found: list[AllergyMatch] = []
    names = [(name, normalize_text(name)) for name in ingredient_names]
    for allergy in allergies:
        for name, key in names:
            if key and _same_substance(allergy.key, key):
                found.append(AllergyMatch(allergy.ingredient, name))
    return found
