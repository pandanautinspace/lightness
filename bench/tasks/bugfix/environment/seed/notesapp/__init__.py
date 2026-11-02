"""notesapp - a tiny personal notes API backed by SQLite."""

from flask import Flask

from . import db

__version__ = "0.3.1"


def create_app(db_path=None, **config):
    """Application factory.

    `db_path` is the SQLite file to use. If not given we fall back to
    NOTES_DB in the environment, then to ./notes.db.
    """
    import os

    app = Flask(__name__)
    app.config.update(
        DATABASE=db_path or os.environ.get("NOTES_DB", "notes.db"),
        JSON_SORT_KEYS=False,
        DEFAULT_PER_PAGE=20,
        MAX_PER_PAGE=100,
    )
    app.config.update(config)

    db.init_app(app)
    with app.app_context():
        db.init_db()

    from .routes import bp

    app.register_blueprint(bp)

    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__}

    return app
