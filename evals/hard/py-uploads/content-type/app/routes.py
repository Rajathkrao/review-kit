import mimetypes

from flask import Blueprint, abort, jsonify, request, send_from_directory

from .storage import list_files, project_dir, save_upload
from .validators import InvalidSlug

bp = Blueprint("assets", __name__)


@bp.errorhandler(InvalidSlug)
def bad_slug(exc):
    return jsonify(error="invalid project"), 400


@bp.post("/projects/<slug>/files")
def upload(slug):
    f = request.files.get("file")
    if f is None:
        abort(400)
    try:
        name = save_upload(slug, f.filename or "", f.stream)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(name=name), 201


@bp.get("/projects/<slug>/files")
def index(slug):
    return jsonify(files=list_files(slug))


# Only these are shown inline; anything else (HTML, SVG, XML, scripts, unknown types) is a
# download, so nothing an uploader controls can render as a page on our origin.
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "text/plain"}


def content_type_for(name: str) -> str:
    guessed, encoding = mimetypes.guess_type(name, strict=False)
    if encoding or not guessed:
        # "notes.txt.gz" guesses text/plain + gzip; serving that as text/plain shows raw bytes.
        return "application/octet-stream"
    return guessed


@bp.get("/projects/<slug>/files/<name>")
def download(slug, name):
    mimetype = content_type_for(name)
    resp = send_from_directory(project_dir(slug), name, mimetype=mimetype,
                               as_attachment=mimetype not in INLINE_TYPES)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp
