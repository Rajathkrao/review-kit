from ..registry import register_legacy_aliases
from . import email, report, webhook  # noqa: F401  (registers handlers)

register_legacy_aliases()
