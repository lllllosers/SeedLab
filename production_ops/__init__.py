"""Offline production operations; package sources stay outside the executor."""


class OperationsError(ValueError):
    """A message suitable for a production operator; technical detail goes to logs."""
