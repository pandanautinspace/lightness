"""JSON API."""

from flask import Blueprint, abort, current_app, jsonify, request

from . import repository as repo
from .db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        abort(400, description=f"{name} must be an integer")
    if value < 1:
        abort(400, description=f"{name} must be >= 1")
    return value


def _payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, description="expected a JSON object")
    return data


@bp.errorhandler(400)
@bp.errorhandler(404)
def json_error(err):
    return jsonify(error=err.description), err.code


@bp.get("/notes")
def list_notes():
    page = _int_arg("page", 1)
    per_page = min(
        _int_arg("per_page", current_app.config["DEFAULT_PER_PAGE"]),
        current_app.config["MAX_PER_PAGE"],
    )
    result = repo.list_notes(
        get_db(),
        page=page,
        per_page=per_page,
        tag=request.args.get("tag") or None,
        q=request.args.get("q") or None,
    )
    return jsonify(result.to_dict())


@bp.post("/notes")
def create_note():
    data = _payload()
    title = (data.get("title") or "").strip()
    if not title:
        abort(400, description="title is required")
    note = repo.create_note(get_db(), title, data.get("body") or "", data.get("tags"))
    return jsonify(note), 201


@bp.get("/notes/<int:note_id>")
def get_note(note_id):
    note = repo.get_note(get_db(), note_id)
    if note is None:
        abort(404, description="note not found")
    return jsonify(note)


@bp.route("/notes/<int:note_id>", methods=["PUT", "PATCH"])
def update_note(note_id):
    data = _payload()
    if "title" in data and not (data["title"] or "").strip():
        abort(400, description="title cannot be empty")
    note = repo.update_note(
        get_db(),
        note_id,
        title=data["title"].strip() if "title" in data else None,
        body=data.get("body"),
        tags=data.get("tags"),
    )
    if note is None:
        abort(404, description="note not found")
    return jsonify(note)


@bp.delete("/notes/<int:note_id>")
def delete_note(note_id):
    if not repo.delete_note(get_db(), note_id):
        abort(404, description="note not found")
    return "", 204


@bp.get("/tags")
def list_tags():
    return jsonify(repo.tag_counts(get_db()))


@bp.get("/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        abort(400, description="q is required")
    per_page = min(_int_arg("per_page", current_app.config["DEFAULT_PER_PAGE"]), current_app.config["MAX_PER_PAGE"])
    result = repo.list_notes(get_db(), page=_int_arg("page", 1), per_page=per_page, q=q)
    return jsonify(result.to_dict())
