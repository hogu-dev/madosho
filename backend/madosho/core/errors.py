class MadoshoError(Exception):
    """Base for all madosho errors."""


class ConfigError(MadoshoError):
    """Bad madosho.yaml: unknown keys, invalid options, type mismatches."""


class UnknownComponentError(ConfigError):
    """Config names a component the registry has never heard of."""


class MissingDependencyError(ConfigError):
    """Component exists but its import failed; message carries the pip fix."""


class ComponentDeniedError(MadoshoError):
    """A resolution hook vetoed this component."""


class CapabilityError(MadoshoError):
    """An operator needs a store capability the configured store lacks."""
