"""Equivalence rules: pure functions, no I/O.

Two products are EQUIVALENT only when all three dimensions are positively the same:
  1. the same set of active ingredients,
  2. the same strength per ingredient after unit normalization,
  3. the same dosage-form family.
Any known difference makes them NOT_EQUIVALENT. Anything unknown (unresolved ingredient, missing
strength, unknown family) with no known difference is POSSIBLE_NEEDS_PHARMACIST_CHECK, never
EQUIVALENT. This is information for a pharmacist, not medical advice.
"""

from dataclasses import dataclass
from enum import StrEnum

from pharmavique.substitution.domain.spec import ProductSpec


class Match(StrEnum):
    EQUIVALENT = "equivalent"
    POSSIBLE_NEEDS_PHARMACIST_CHECK = "possible_needs_pharmacist_check"
    NOT_EQUIVALENT = "not_equivalent"


class Finding(StrEnum):
    SAME = "same"
    DIFFERENT = "different"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Equivalence:
    verdict: Match
    ingredients: Finding
    strength: Finding
    form_family: Finding


def _ingredients(a: ProductSpec, b: ProductSpec) -> Finding:
    if len(a.ingredients) != len(b.ingredients):
        return Finding.DIFFERENT
    if any(i.ingredient_id is None for i in (*a.ingredients, *b.ingredients)):
        return Finding.UNKNOWN
    ids_a = {i.ingredient_id for i in a.ingredients}
    ids_b = {i.ingredient_id for i in b.ingredients}
    return Finding.SAME if ids_a == ids_b else Finding.DIFFERENT


def _strength(a: ProductSpec, b: ProductSpec, ingredients: Finding) -> Finding:
    if ingredients is not Finding.SAME:
        return Finding.UNKNOWN  # ingredients cannot be paired, so strengths are not compared
    strength_b = {i.ingredient_id: i.strength for i in b.ingredients}
    result = Finding.SAME
    for item in a.ingredients:
        left = item.strength
        right = strength_b[item.ingredient_id]
        if left is None or right is None:
            result = Finding.UNKNOWN
        elif left.normalized() != right.normalized():
            return Finding.DIFFERENT
    return result


def _form_family(a: ProductSpec, b: ProductSpec) -> Finding:
    if a.form_family is None or b.form_family is None:
        return Finding.UNKNOWN
    return Finding.SAME if a.form_family == b.form_family else Finding.DIFFERENT


def assess(a: ProductSpec, b: ProductSpec) -> Equivalence:
    ingredients = _ingredients(a, b)
    strength = _strength(a, b, ingredients)
    form_family = _form_family(a, b)
    findings = (ingredients, strength, form_family)

    if Finding.DIFFERENT in findings:
        verdict = Match.NOT_EQUIVALENT
    elif Finding.UNKNOWN in findings:
        verdict = Match.POSSIBLE_NEEDS_PHARMACIST_CHECK
    else:
        verdict = Match.EQUIVALENT
    return Equivalence(verdict, ingredients, strength, form_family)
