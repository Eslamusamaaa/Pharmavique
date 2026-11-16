from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from pharmavique.shared_kernel.errors import InvariantViolation
from pharmavique.shared_kernel.events import DomainEvent, IntegrationEvent
from pharmavique.shared_kernel.principal import Principal, Role
from pharmavique.shared_kernel.provenance import Provenance, TrustLevel

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_provenance(**overrides: object) -> Provenance:
    fields: dict[str, object] = {
        "source": "sfda-file",
        "source_ref": "file://dump-2026-01-01.csv",
        "fetched_at": NOW,
        "snapshot_id": "snap-001",
        "trust": TrustLevel.OFFICIAL,
    }
    fields.update(overrides)
    return Provenance(**fields)  # type: ignore[arg-type]


def test_trust_levels_match_the_brief() -> None:
    assert {t.value for t in TrustLevel} == {"official", "unofficial_unverified"}


def test_provenance_holds_all_required_fields() -> None:
    provenance = make_provenance()

    assert provenance.source == "sfda-file"
    assert provenance.snapshot_id == "snap-001"
    assert provenance.trust is TrustLevel.OFFICIAL


def test_provenance_is_immutable() -> None:
    provenance = make_provenance()

    with pytest.raises(FrozenInstanceError):
        provenance.source = "other"  # type: ignore[misc]


@pytest.mark.parametrize("field", ["source", "source_ref", "snapshot_id"])
def test_provenance_rejects_blank_text_fields(field: str) -> None:
    with pytest.raises(InvariantViolation):
        make_provenance(**{field: "  "})


def test_provenance_requires_timezone_aware_fetched_at() -> None:
    with pytest.raises(InvariantViolation):
        make_provenance(fetched_at=datetime(2026, 1, 1, 12, 0))


def test_domain_event_gets_a_unique_id() -> None:
    first = DomainEvent(occurred_at=NOW)
    second = DomainEvent(occurred_at=NOW)

    assert isinstance(first.event_id, UUID)
    assert first.event_id != second.event_id


def test_events_require_timezone_aware_timestamps() -> None:
    with pytest.raises(InvariantViolation):
        DomainEvent(occurred_at=datetime(2026, 1, 1))


def test_integration_event_defaults_to_schema_version_one() -> None:
    assert IntegrationEvent(occurred_at=NOW).schema_version == 1


def test_integration_event_rejects_schema_version_below_one() -> None:
    with pytest.raises(InvariantViolation):
        IntegrationEvent(occurred_at=NOW, schema_version=0)


def test_principal_needs_at_least_one_role() -> None:
    with pytest.raises(InvariantViolation):
        Principal(user_id=uuid4(), tenant_id=None, roles=frozenset())


def test_principal_may_have_no_tenant_for_patients() -> None:
    principal = Principal(user_id=uuid4(), tenant_id=None, roles=frozenset({Role.PATIENT}))

    assert principal.tenant_id is None
    assert Role.PATIENT in principal.roles


def test_roles_are_patient_pharmacist_company() -> None:
    assert {r.value for r in Role} == {"patient", "pharmacist", "company"}
