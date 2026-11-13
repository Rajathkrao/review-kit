import os

from flask import Blueprint, abort, current_app, jsonify, request, send_file

from .bundles import BundleError, BundleTooLarge, extract_bundle
from .storage import list_files, project_dir, save_upload
from .validators import InvalidSlug, check_slug, slug_from_form

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


@bp.post("/bundles")
@slug_from_form("project")
def upload_bundle(slug):
    if request.content_length > current_app.config["MAX_BUNDLE_BYTES"]:
        return jsonify(error="bundle too large"), 413
    f = request.files.get("bundle")
    if f is None:
        abort(400)
    try:
        files = extract_bundle(slug, f.stream)
    except BundleTooLarge as exc:
        return jsonify(error=str(exc)), 413
    except BundleError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(project=slug, files=files), 201


@bp.get("/projects/<slug>/files")
def index(slug):
    return jsonify(files=list_files(slug))


@bp.get("/projects/<slug>/files/<path:relpath>")
def download(slug, relpath):
    # send_from_directory only serves a flat name; bundles have folders, so resolve it here.
    root = str(project_dir(check_slug(slug)))
    full = os.path.join(root, relpath)
    if not full.startswith(root):
        abort(404)
    if not os.path.isfile(full):
        abort(404)
    return send_file(full)
