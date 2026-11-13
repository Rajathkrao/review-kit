import re

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")


class InvalidSlug(ValueError):
    pass


def check_slug(slug: str) -> str:
    """Project slugs: 3-40 chars, lowercase letters, digits and dashes, not starting with a dash."""
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise InvalidSlug(slug)
    return slug
