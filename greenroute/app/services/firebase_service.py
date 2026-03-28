"""
firebase_service.py — Push GreenRouteDecision to Firebase Realtime Database.

Requires the optional `firebase-admin` package:
    uv add firebase-admin

If the package is not installed or credentials are not configured, the push is
skipped silently and the function returns None.

Firebase path written:
    decisions/{corridor_id}/{YYYY-MM-DD}/{decision_id}

This allows retrieving all decisions for a corridor on a given day via
the REST endpoint:
    GET {FIREBASE_URL}/decisions/{corridor_id}/{YYYY-MM-DD}.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def push_decision(
    decision_dict: dict[str, Any],
    firebase_url: str,
    credentials_file: str,
) -> str | None:
    """
    Push a GreenRouteDecision dict to Firebase Realtime Database.

    Args:
        decision_dict   : GreenRouteDecision serialised to a plain dict.
        firebase_url    : e.g. "https://project-default-rtdb.firebaseio.com"
        credentials_file: Path to the Firebase service account JSON key file.

    Returns:
        The Firebase path string where the data was written, e.g.
        "decisions/SGP_PKL/2026-03-28/<decision_id>", or None on failure.
    """
    if not firebase_url or not credentials_file:
        logger.info(
            "Firebase not configured (FIREBASE_URL or FIREBASE_CREDENTIALS_FILE "
            "missing) — skipping push."
        )
        return None

    try:
        import firebase_admin                               # type: ignore[import]
        from firebase_admin import credentials, db          # type: ignore[import]
    except ImportError:
        logger.warning(
            "firebase-admin is not installed. "
            "Run `uv add firebase-admin` to enable Firebase push. "
            "Skipping."
        )
        return None

    try:
        # Initialise the app once; reuse if already initialised.
        try:
            app = firebase_admin.get_app()
        except ValueError:
            cred = credentials.Certificate(credentials_file)
            app = firebase_admin.initialize_app(
                cred, {"databaseURL": firebase_url}
            )

        corridor_id  = decision_dict.get("corridor_id", "UNKNOWN")
        decision_id  = decision_dict.get("decision_id", "unknown")
        ts_raw       = decision_dict.get("timestamp")
        date_str     = _date_str(ts_raw)

        fb_path = f"decisions/{corridor_id}/{date_str}/{decision_id}"
        ref = db.reference(fb_path, app=app)

        # Firebase Realtime DB requires JSON-serialisable values.
        payload = json.loads(json.dumps(decision_dict, default=str))
        ref.set(payload)

        logger.info("Pushed GreenRouteDecision to Firebase: %s", fb_path)
        return fb_path

    except Exception as exc:                                # noqa: BLE001
        logger.error("Firebase push failed: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _date_str(ts: Any) -> str:
    """Return YYYY-MM-DD from an ISO string, datetime, or today as fallback."""
    if ts is None:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%d")
    try:
        return str(ts)[:10]   # first 10 chars of ISO string
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
