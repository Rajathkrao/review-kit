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


# Types a browser would execute or render as a page on our origin. Serve them as downloads.
ACTIVE_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml", "text/xml",
                "application/xml", "application/javascript", "text/javascript"}


def content_type_for(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name, strict=False)
    return guessed or "application/octet-stream"


@bp.get("/projects/<slug>/files/<name>")
def download(slug, name):
    mimetype = content_type_for(name)
    resp = send_from_directory(project_dir(slug), name, mimetype=mimetype,
                               as_attachment=mimetype in ACTIVE_TYPES)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return resp
