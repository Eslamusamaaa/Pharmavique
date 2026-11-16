"""Base errors shared by every context."""


class DomainError(Exception):
    """Base class for all domain errors."""


class InvariantViolation(DomainError):
    """A value or entity was built in a state the domain forbids."""
