import os
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from .validators import check_slug


def project_dir(slug: str, create: bool = False) -> Path:
    path = Path(current_app.config["STORAGE_ROOT"]) / check_slug(slug)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def save_upload(slug: str, filename: str, stream) -> str:
    name = secure_filename(filename)
    if not name:
        raise ValueError("empty file name")
    dest = project_dir(slug, create=True) / name
    limit = current_app.config["MAX_FILE_BYTES"]
    written = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as fh:
        while chunk := stream.read(64 * 1024):
            written += len(chunk)
            if written > limit:
                fh.close()
                tmp.unlink()
                raise ValueError("file too large")
            fh.write(chunk)
    os.replace(tmp, dest)
    return name


def list_files(slug: str) -> list[str]:
    root = project_dir(slug)
    if not root.is_dir():
        return []
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
