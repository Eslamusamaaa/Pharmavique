"""Matching our registry's ingredient names to the names an interaction source uses."""

import pytest

from pharmavique.interactions.domain.names import base_key, candidate_keys


@pytest.mark.parametrize(
    ("registry_name", "expected_first"),
    [
        ("AMLODIPINE BESILATE", "amlodipine besilate"),
        ("  Losartan   Potassium ", "losartan potassium"),
        ("DL-ALPHA TOCOFERIL ACETATE", "dl alpha tocoferil acetate"),
    ],
)
def test_the_first_candidate_is_the_name_as_written_but_normalized(
    registry_name: str, expected_first: str
) -> None:
    assert candidate_keys(registry_name)[0] == expected_first


@pytest.mark.parametrize(
    ("registry_name", "base"),
    [
        ("AMLODIPINE BESILATE", "amlodipine"),
        ("METFORMIN HYDROCHLORIDE", "metformin"),
        ("LOSARTAN POTASSIUM", "losartan"),
        ("MORPHINE SULFATE", "morphine"),
        ("OLMESARTAN MEDOXOMIL", "olmesartan"),
        ("CEFUROXIME AXETIL", "cefuroxime"),
        ("DABIGATRAN ETEXILATE", "dabigatran"),
        ("MOMETASONE FUROATE", "mometasone"),
        ("PYRIDOXINE (VITAMIN B6)", "pyridoxine"),
        ("PARACETAMOL", "acetaminophen"),
        ("CEFALEXIN", "cephalexin"),
        ("COLECALCIFEROL", "cholecalciferol"),
        ("SODIUM CHLORIDE", "sodium chloride"),  # a bare anion is no drug name
        ("POTASSIUM CHLORIDE", "potassium chloride"),
        ("CALCIUM CHLORIDE", "calcium chloride"),
    ],
)
def test_salts_esters_and_inn_spellings_resolve_to_the_name_sources_use(
    registry_name: str, base: str
) -> None:
    assert base_key(registry_name) == base


def test_every_spelling_to_try_is_offered_once_and_in_order() -> None:
    keys = candidate_keys("PARACETAMOL")

    assert keys == ("paracetamol", "acetaminophen")
    assert len(keys) == len(set(keys))


def test_an_empty_name_has_no_candidates() -> None:
    assert candidate_keys("  ") == ()
    assert base_key("") == ""
