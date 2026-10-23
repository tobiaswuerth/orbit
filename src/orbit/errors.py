class OrbitError(ValueError):
    """An error the caller can act on. Its message says what went wrong and what to do next."""


class VaultInUse(OrbitError):
    """Another orbit process has the vault open: one writer per vault."""
