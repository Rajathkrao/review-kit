"""Small admin API (docs/ingest-v2.md #9)."""
import hmac
import os

from flask import Flask, abort, jsonify, request

from .config import Settings
from .store import Store
from .worker import run_file


def require_token(settings: Settings):
    def deco(view):
        def wrapper(*args, **kwargs):
            if not settings.api_token:
                abort(503)          # never run the admin API without a token configured
            given = request.headers.get("Authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(given.encode(), settings.api_token.encode()):
                abort(401)
            return view(*args, **kwargs)
        return wrapper
    return deco


def create_app(store: Store, settings: Settings | None = None) -> Flask:
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    auth = require_token(settings)

    @app.get("/stats")
    @auth
    def stats():
        return jsonify(events=store.count_events(), usage=store.usage())

    @app.post("/replay/<name>")
    @auth
    def replay(name):
        if "/" in name or name.startswith("."):
            abort(400)
        path = os.path.join(settings.inbox, name)
        if not os.path.isfile(path):
            abort(404)
        return jsonify(run_file(path, store, settings))

    return app
