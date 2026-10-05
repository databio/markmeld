"""Custom exceptions for the markmeld package."""


class TargetError(Exception):
    """Raised when there is a problem with a build target."""

    pass


class ConfigError(Exception):
    """Raised when there is a problem with the configuration file."""

    pass


class BibliographyFetchError(Exception):
    """Raised when a target's Drive bibliography is not in its Drive folder."""

    pass
