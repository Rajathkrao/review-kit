import re
from functools import wraps

from flask import request

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{2,39}")


class InvalidSlug(ValueError):
    pass


def check_slug(slug: str) -> str:
    """Project slugs: 3-40 chars, lowercase letters, digits and dashes, not starting with a dash."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise InvalidSlug(slug)
    return slug


def slug_from_form(field: str = "project"):
    """Decorator: validate request.form[field] and pass it to the view as `slug`."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            kwargs["slug"] = check_slug(request.form.get(field, ""))
            return view(*args, **kwargs)
        return wrapper
    return deco
