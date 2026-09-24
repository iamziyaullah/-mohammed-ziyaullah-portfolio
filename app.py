"""Mohammed Ziyaullah's portfolio + private, server-side content studio.

The login password is NEVER sent to the public page or kept in source code.
Set FLASK_SECRET_KEY and COOKIE_SECURE=1 when deploying behind HTTPS.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher, exceptions as argon_errors
from flask import (
    Flask, abort, g, jsonify, redirect, render_template, request, send_file,
    session, url_for,
)
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "site.db"
SEED_PATH = ROOT / "data" / "seed.json"
UPLOAD_PATH = ROOT / "uploads" / "profile.jpg"
PH = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 8
_login_failures: dict[str, list[float]] = {}


class ContentError(ValueError):
    """An admin edit failed validation."""


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        path = Path(g.app.config["DATABASE"])
        path.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def init_db(app: Flask) -> None:
    path = Path(app.config["DATABASE"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS admin (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                auth_version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                saved_at TEXT NOT NULL
            );
        """)
        exists = db.execute("SELECT id FROM content WHERE id = 1").fetchone()
        if not exists:
            seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO content(id,data,version,updated_at) VALUES(1,?,?,?)",
                (json.dumps(seed, ensure_ascii=False), 1, utc_now()),
            )
        db.commit()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def set_admin_credentials(db_path: Path | str, email: str, password: str) -> None:
    """Seed/update an account with Argon2id; no plaintext credential is persisted."""
    email = check_email(email)
    if len(password) < 12 or len(password) > 200:
        raise ValueError("Use a password of at least 12 characters.")
    hashed = PH.hash(password)
    with closing(sqlite3.connect(db_path, timeout=10)) as db, db:
        db.execute("""
            INSERT INTO admin(id,email,password_hash,auth_version,updated_at)
            VALUES(1,?,?,1,?)
            ON CONFLICT(id) DO UPDATE SET
                email=excluded.email,
                password_hash=excluded.password_hash,
                auth_version=auth_version+1,
                updated_at=excluded.updated_at
        """, (email, hashed, utc_now()))
        db.commit()


def plain_text(value: object, name: str, max_length: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ContentError(f"{name} must be text.")
    value = value.strip()
    if required and not value:
        raise ContentError(f"{name} cannot be blank.")
    if len(value) > max_length:
        raise ContentError(f"{name} is too long (max {max_length} characters).")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise ContentError(f"{name} contains an invalid control character.")
    return value


def check_email(value: object) -> str:
    email = plain_text(value, "Email", 254).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ContentError("Please enter a valid email address.")
    return email


def https_url(value: object, name: str) -> str:
    url = plain_text(value, name, 1500)
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ContentError(f"{name} must be a valid HTTPS URL.")
    return url


def list_of(value: object, name: str, limit: int) -> list:
    if not isinstance(value, list) or len(value) > limit:
        raise ContentError(f"{name} must be a list with at most {limit} items.")
    return value


def validate_content(raw: object) -> dict:
    """Whitelisted schema, sensible limits and URL validation; templates escape all text."""
    if not isinstance(raw, dict):
        raise ContentError("Content must be an object.")
    p = raw.get("profile")
    a = raw.get("about")
    if not isinstance(p, dict) or not isinstance(a, dict):
        raise ContentError("Profile and story are required.")
    profile = {}
    limits = {
        "name": 90, "role": 170, "hero_headline": 130, "hero_highlight": 100,
        "hero_description": 600, "hero_secondary": 600, "location": 80,
        "cta_title": 150, "cta_description": 550, "quote": 600,
    }
    for key, limit in limits.items():
        profile[key] = plain_text(p.get(key), f"Profile / {key}", limit)
    profile["email"] = check_email(p.get("email"))
    phone = plain_text(p.get("phone"), "Phone", 20)
    digits = re.sub(r"\D", "", phone)
    if not (10 <= len(digits) <= 15):
        raise ContentError("Phone needs 10–15 digits.")
    profile["phone"] = digits
    profile["linkedin"] = https_url(p.get("linkedin"), "LinkedIn URL")

    about = {
        "title": plain_text(a.get("title"), "Story heading", 180),
        "intro": plain_text(a.get("intro"), "Story introduction", 2000),
        "paragraphs": [plain_text(text, "Story paragraph", 2200) for text in list_of(a.get("paragraphs"), "Story paragraphs", 25)],
    }
    metrics = []
    for item in list_of(raw.get("metrics"), "Metrics", 12):
        if not isinstance(item, dict):
            raise ContentError("Each metric needs a value and label.")
        metrics.append({
            "value": plain_text(item.get("value"), "Metric value", 28),
            "label": plain_text(item.get("label"), "Metric label", 80),
        })
    brands = [plain_text(name, "Organization", 100) for name in list_of(raw.get("brands"), "Organizations", 20)]
    services = []
    for item in list_of(raw.get("services"), "Services", 20):
        if not isinstance(item, dict):
            raise ContentError("Each service must be an object.")
        paragraphs = [plain_text(x, "Service paragraph", 2200) for x in list_of(item.get("paragraphs"), "Service paragraphs", 6)]
        services.append({"title": plain_text(item.get("title"), "Service title", 120), "paragraphs": paragraphs})
    experience = []
    for item in list_of(raw.get("experience"), "Experience", 25):
        if not isinstance(item, dict):
            raise ContentError("Each role must be an object.")
        experience.append({
            "role": plain_text(item.get("role"), "Job title", 130),
            "company": plain_text(item.get("company"), "Company", 150),
            "dates": plain_text(item.get("dates"), "Dates", 100),
            "bullets": [plain_text(x, "Role highlight", 650) for x in list_of(item.get("bullets"), "Role highlights", 15)],
        })
    certifications = []
    for item in list_of(raw.get("certifications"), "Certifications", 50):
        if not isinstance(item, dict):
            raise ContentError("Each certification must be an object.")
        certifications.append({
            "title": plain_text(item.get("title"), "Certificate title", 180),
            "issuer": plain_text(item.get("issuer"), "Issuer", 100),
            "category": plain_text(item.get("category"), "Category", 70),
            "url": https_url(item.get("url"), "Certificate URL"),
        })
    skills = []
    for item in list_of(raw.get("skills"), "Skills", 30):
        if not isinstance(item, dict):
            raise ContentError("Each skill must be an object.")
        value = item.get("percent")
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
            raise ContentError("Skill percentage must be between 0 and 100.")
        skills.append({"label": plain_text(item.get("label"), "Skill", 95), "percent": value})
    return {
        "profile": profile, "about": about, "metrics": metrics, "brands": brands,
        "services": services, "experience": experience, "certifications": certifications,
        "skills": skills,
    }


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    secret = os.environ.get("FLASK_SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        logging.warning("Using an ephemeral session secret for preview. Set FLASK_SECRET_KEY for deployment.")
    app.config.update(
        SECRET_KEY=secret,
        DATABASE=str(Path(os.environ.get("ZIYA_DB_PATH", str(DEFAULT_DB)))),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        JSON_AS_ASCII=False,
    )
    if test_config:
        app.config.update(test_config)
    init_db(app)
    # One-time deployment bootstrap. Set this secret in the HOST's environment,
    # never in GitHub or source files, then remove it after the first successful boot.
    first_password = os.environ.get("INITIAL_ADMIN_PASSWORD")
    if first_password:
        with closing(sqlite3.connect(app.config["DATABASE"], timeout=10)) as db:
            already_configured = db.execute("SELECT id FROM admin WHERE id=1").fetchone()
        if not already_configured:
            set_admin_credentials(
                app.config["DATABASE"],
                os.environ.get("INITIAL_ADMIN_EMAIL", "ziyaullahshahid@gmail.com"),
                first_password,
            )
            logging.warning("Admin account initialized. Remove INITIAL_ADMIN_PASSWORD from hosting environment now.")

    @app.before_request
    def attach_app() -> None:
        g.app = app

    @app.teardown_appcontext
    def close_db(_exc: Exception | None) -> None:
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; "
            "connect-src 'self'; base-uri 'self'; object-src 'none'; "
            "form-action 'self' mailto:"
        )
        if request.path.startswith("/admin") or request.path.startswith("/api/admin"):
            response.headers["Cache-Control"] = "no-store, private"
        return response

    def get_content_row() -> sqlite3.Row:
        return get_db().execute("SELECT data,version,updated_at FROM content WHERE id=1").fetchone()

    def content_and_version() -> tuple[dict, int, str]:
        row = get_content_row()
        return json.loads(row["data"]), row["version"], row["updated_at"]

    def csrf_token() -> str:
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def csrf_ok() -> bool:
        submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        expected = session.get("csrf", "")
        return bool(expected) and secrets.compare_digest(expected, submitted)

    def admin_row() -> sqlite3.Row | None:
        admin_id = session.get("admin_id")
        if admin_id != 1:
            return None
        row = get_db().execute("SELECT id,email,auth_version FROM admin WHERE id=1").fetchone()
        if not row or session.get("auth_version") != row["auth_version"]:
            session.clear()
            return None
        return row

    def require_admin(json_api: bool = False) -> sqlite3.Row | None:
        row = admin_row()
        if not row:
            if json_api:
                abort(401)
            return None
        return row

    def require_csrf() -> None:
        if not csrf_ok():
            abort(403, description="Invalid security token. Refresh the page and try again.")

    def portrait_url() -> str:
        if UPLOAD_PATH.exists():
            return url_for("portrait", v=UPLOAD_PATH.stat().st_mtime_ns)
        return url_for("static", filename="images/ziyaullah.jpg")

    @app.get("/")
    def homepage():
        data, _, _ = content_and_version()
        categories = list(dict.fromkeys(c["category"] for c in data["certifications"]))
        response = app.make_response(render_template(
            "site.html", site=data, categories=categories,
            portrait_url=portrait_url(), year=datetime.now().year,
        ))
        response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/media/profile.jpg")
    def portrait():
        if not UPLOAD_PATH.exists():
            abort(404)
        return send_file(UPLOAD_PATH, mimetype="image/jpeg", max_age=3600)

    @app.get("/robots.txt")
    def robots():
        return app.response_class("User-agent: *\nDisallow: /admin\nDisallow: /api/admin\n", mimetype="text/plain")

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/admin/login", methods=["GET", "POST"])
    def login():
        if admin_row():
            return redirect(url_for("admin_dashboard"))
        if request.method == "GET":
            return render_template("login.html", csrf=csrf_token(), error=None, email="")
        require_csrf()
        supplied_email = request.form.get("email", "").strip().lower()
        supplied_password = request.form.get("password", "")
        ip = request.remote_addr or "unknown"
        now = time.monotonic()
        attempts = [t for t in _login_failures.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
        _login_failures[ip] = attempts
        if len(attempts) >= LOGIN_MAX_ATTEMPTS:
            resp = render_template("login.html", csrf=csrf_token(), error="Too many attempts. Try again in 15 minutes.", email=supplied_email)
            return resp, 429, {"Retry-After": str(LOGIN_WINDOW_SECONDS)}
        row = get_db().execute("SELECT * FROM admin WHERE id=1").fetchone()
        authenticated = False
        if row and secrets.compare_digest(supplied_email, row["email"]):
            try:
                authenticated = PH.verify(row["password_hash"], supplied_password)
            except (argon_errors.VerifyMismatchError, argon_errors.VerificationError, ValueError):
                authenticated = False
        if not authenticated:
            attempts.append(now)
            _login_failures[ip] = attempts
            return render_template("login.html", csrf=csrf_token(), error="Incorrect email or password.", email=supplied_email), 401
        _login_failures.pop(ip, None)
        if PH.check_needs_rehash(row["password_hash"]):
            get_db().execute("UPDATE admin SET password_hash=? WHERE id=1", (PH.hash(supplied_password),))
            get_db().commit()
        session.clear()
        session.permanent = True
        session["admin_id"] = 1
        session["auth_version"] = row["auth_version"]
        session["csrf"] = secrets.token_urlsafe(32)
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/logout")
    def logout():
        if not require_admin():
            return redirect(url_for("login"))
        require_csrf()
        session.clear()
        return redirect(url_for("login"))

    @app.get("/admin")
    def admin_dashboard():
        admin = require_admin()
        if not admin:
            return redirect(url_for("login", next="admin"))
        data, version, updated = content_and_version()
        return render_template(
            "admin.html", site=data, version=version, updated=updated,
            csrf=csrf_token(), admin_email=admin["email"], portrait_url=portrait_url(),
        )

    @app.get("/api/admin/content")
    def api_content():
        require_admin(json_api=True)
        data, version, updated = content_and_version()
        return jsonify(content=data, version=version, updated=updated, portrait_url=portrait_url())

    @app.put("/api/admin/content")
    def api_save():
        require_admin(json_api=True)
        require_csrf()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Send valid JSON."), 400
        try:
            updated_content = validate_content(payload.get("content"))
        except ContentError as exc:
            return jsonify(error=str(exc)), 400
        version = payload.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            return jsonify(error="Missing version. Refresh and try again."), 400
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data,version FROM content WHERE id=1").fetchone()
            if version != row["version"]:
                db.rollback()
                return jsonify(error="This site was edited elsewhere. Refresh before saving."), 409
            db.execute("INSERT INTO revisions(data,saved_at) VALUES(?,?)", (row["data"], utc_now()))
            db.execute("UPDATE content SET data=?,version=?,updated_at=? WHERE id=1", (
                json.dumps(updated_content, ensure_ascii=False), version + 1, utc_now(),
            ))
            db.execute("DELETE FROM revisions WHERE id NOT IN (SELECT id FROM revisions ORDER BY id DESC LIMIT 20)")
            db.commit()
        except sqlite3.Error:
            db.rollback()
            logging.exception("Could not save site content")
            return jsonify(error="Could not save. Try again."), 500
        return jsonify(ok=True, version=version + 1, updated=utc_now())

    @app.get("/api/admin/revisions")
    def api_revisions():
        require_admin(json_api=True)
        rows = get_db().execute("SELECT id,saved_at FROM revisions ORDER BY id DESC LIMIT 20").fetchall()
        return jsonify(revisions=[dict(x) for x in rows])

    @app.post("/api/admin/revisions/<int:revision_id>/restore")
    def api_restore(revision_id: int):
        require_admin(json_api=True)
        require_csrf()
        db = get_db()
        try:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT data FROM revisions WHERE id=?", (revision_id,)).fetchone()
            if not old:
                db.rollback()
                abort(404, description="Revision not found.")
            current = db.execute("SELECT data,version FROM content WHERE id=1").fetchone()
            db.execute("INSERT INTO revisions(data,saved_at) VALUES(?,?)", (current["data"], utc_now()))
            db.execute("UPDATE content SET data=?,version=?,updated_at=? WHERE id=1", (
                old["data"], current["version"] + 1, utc_now(),
            ))
            db.execute("DELETE FROM revisions WHERE id NOT IN (SELECT id FROM revisions ORDER BY id DESC LIMIT 20)")
            db.commit()
        except sqlite3.Error:
            db.rollback()
            logging.exception("Could not restore revision")
            return jsonify(error="Could not restore."), 500
        return jsonify(ok=True, version=current["version"] + 1)

    @app.post("/api/admin/password")
    def api_password():
        admin = require_admin(json_api=True)
        require_csrf()
        payload = request.get_json(silent=True) or {}
        current = payload.get("current", "")
        new = payload.get("new", "")
        if not isinstance(current, str) or not isinstance(new, str):
            return jsonify(error="Invalid password input."), 400
        if not (12 <= len(new) <= 200):
            return jsonify(error="New password must be at least 12 characters."), 400
        if current == new:
            return jsonify(error="Choose a different password."), 400
        row = get_db().execute("SELECT password_hash,auth_version FROM admin WHERE id=?", (admin["id"],)).fetchone()
        try:
            PH.verify(row["password_hash"], current)
        except (argon_errors.VerifyMismatchError, argon_errors.VerificationError, ValueError):
            return jsonify(error="Current password is incorrect."), 400
        db = get_db()
        db.execute("UPDATE admin SET password_hash=?,auth_version=auth_version+1,updated_at=? WHERE id=1", (
            PH.hash(new), utc_now(),
        ))
        db.commit()
        session["auth_version"] = row["auth_version"] + 1
        return jsonify(ok=True, message="Password changed. Other sessions have been signed out.")

    @app.post("/api/admin/media")
    def api_upload():
        require_admin(json_api=True)
        require_csrf()
        upload = request.files.get("photo")
        if not upload or not upload.filename:
            return jsonify(error="Select a JPG, PNG or WebP image."), 400
        raw = upload.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            return jsonify(error="Maximum image size is 5 MB."), 413
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Unsupported image type")
                if source.width * source.height > 25_000_000:
                    raise ValueError("Image dimensions are too large")
                source.load()
                image = ImageOps.exif_transpose(source)
                if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                    image = image.convert("RGBA")
                    backing = Image.new("RGB", image.size, (245, 242, 236))
                    backing.paste(image, mask=image.getchannel("A"))
                    image = backing
                else:
                    image = image.convert("RGB")
                image.thumbnail((1300, 1600), Image.Resampling.LANCZOS)
                UPLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = UPLOAD_PATH.with_name("portrait-" + secrets.token_hex(6) + ".tmp")
                try:
                    image.save(tmp, format="JPEG", quality=86, optimize=True)
                    os.replace(tmp, UPLOAD_PATH)
                finally:
                    tmp.unlink(missing_ok=True)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            return jsonify(error="Please upload a valid JPG, PNG or WebP image."), 400
        return jsonify(ok=True, portrait_url=portrait_url())

    @app.post("/api/admin/media/reset")
    def api_reset_media():
        require_admin(json_api=True)
        require_csrf()
        UPLOAD_PATH.unlink(missing_ok=True)
        return jsonify(ok=True, portrait_url=portrait_url())

    @app.errorhandler(401)
    @app.errorhandler(403)
    def auth_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(error, "description", "Not authorized.")), error.code
        return render_template("error.html", code=error.code, message=error.description), error.code

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return render_template("error.html", code=404, message="This page doesn't exist."), 404

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="Upload is too large (maximum 5 MB)."), 413

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8002"))
    app.run(host="0.0.0.0", port=port, debug=False)
