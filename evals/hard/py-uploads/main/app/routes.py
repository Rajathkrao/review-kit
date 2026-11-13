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


@bp.get("/projects/<slug>/files/<name>")
def download(slug, name):
    return send_from_directory(project_dir(slug), name)
