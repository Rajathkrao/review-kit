"""Extract uploaded .tar.gz asset bundles into a project's directory (docs/bundles.md)."""
import tarfile
from pathlib import Path

from flask import current_app

from .storage import project_dir


class BundleError(ValueError):
    pass


class BundleTooLarge(BundleError):
    pass


def _check_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = tar.getmembers()
    if len(members) > current_app.config["MAX_BUNDLE_FILES"]:
        raise BundleTooLarge(f"{len(members)} members")
    for m in members:
        name = m.name
        if name.startswith("/") or ".." in Path(name).parts:
            raise BundleError(f"unsafe path in bundle: {name}")
        if m.isdev():
            raise BundleError(f"device file in bundle: {name}")
    return members


def extract_bundle(slug: str, fileobj) -> list[str]:
    """Validate and extract a bundle; returns the extracted file paths relative to the project."""
    dest = project_dir(slug, create=True)
    try:
        tar = tarfile.open(fileobj=fileobj, mode="r:gz")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise BundleError(f"not a .tar.gz bundle: {exc}") from None
    with tar:
        members = _check_members(tar)
        # Every member was validated above, so extraction cannot stop half way through.
        tar.extractall(dest, members=members)
    return sorted(m.name for m in members if m.isfile())
