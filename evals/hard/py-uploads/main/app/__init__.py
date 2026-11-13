from flask import Flask

from .config import Config


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    from .routes import bp
    app.register_blueprint(bp)
    return app
