"""
Authentication routes for ClipVault.
Handles signup, login, logout with Flask sessions.
"""
import secrets
import hashlib
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from models import (
    create_user, get_user_by_email, get_user_by_id,
    create_session, get_session, delete_session,
    get_searches_used,
)

auth_bp = Blueprint("auth", __name__)


def hash_password(password: str) -> str:
    """Hash a password with SHA-256 + salt."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}${h}"


def check_password(password: str, stored_hash: str) -> bool:
    """Verify a password against stored hash."""
    try:
        salt, h = stored_hash.split("$", 1)
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
    except (ValueError, AttributeError):
        return False


def login_user(user_id: int):
    """Create a session for the user."""
    token = secrets.token_hex(32)
    create_session(user_id, token)
    session["auth_token"] = token
    session["user_id"] = user_id


def logout_user():
    """Clear the session."""
    token = session.get("auth_token")
    if token:
        delete_session(token)
    session.pop("auth_token", None)
    session.pop("user_id", None)


def get_current_user() -> dict | None:
    """Get the currently logged-in user, or None."""
    token = session.get("auth_token")
    if not token:
        return None
    sess = get_session(token)
    if not sess:
        return None
    return get_user_by_id(sess["user_id"])


# ── Routes ─────────────────────────────────────────────

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Email and password required.", "error")
            return render_template("login.html")

        user = get_user_by_email(email)
        if not user or not check_password(password, user["password_hash"]):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        login_user(user["id"])
        from models import update_last_login
        update_last_login(user["id"])
        flash("Welcome back!", "success")
        return redirect(url_for("index"))

    return render_template("login.html")


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()

        errors = []
        if not email or "@" not in email:
            errors.append("Valid email required.")
        if len(password) < 6:
            errors.append("Password must be at least 6 characters.")
        if len(name) < 1:
            name = email.split("@")[0]

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("signup.html")

        user_id = create_user(email, hash_password(password), name)
        if user_id is None:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")

        login_user(user_id)
        flash("Account created! Welcome to ClipVault.", "success")
        return redirect(url_for("index"))

    return render_template("signup.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@auth_bp.route("/account")
def account():
    user = get_current_user()
    if not user:
        return redirect(url_for("auth.login"))
    
    from models import get_month_key
    searches_used = get_searches_used(user["id"])
    
    return render_template("account.html", user=user, searches_used=searches_used)
