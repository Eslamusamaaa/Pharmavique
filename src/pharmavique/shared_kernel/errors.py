"""Base errors shared by every context."""


class DomainError(Exception):
    """Base class for all domain errors."""


class InvariantViolation(DomainError):  # noqa: N818 (name chosen for domain language)
    """A value or entity was built in a state the domain forbids."""
