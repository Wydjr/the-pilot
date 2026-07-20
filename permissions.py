import os
import json
import base64
import requests
from typing import Any, Dict, Tuple

# ------------------- GitHub Config -------------------
GITHUB_REPO = os.getenv("GITHUB_REPO", "wydjr/the-pilot")
GITHUB_FILE_PATH = "pilot_settings.json"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}

def _gh_url() -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"

def _ensure_shape(settings: Dict[str, Any]) -> Dict[str, Any]:
    settings.setdefault("global_allowed_roles", [])
    settings.setdefault("apps", {})
    for k, v in DEFAULT_SETTINGS["apps"].items():
        settings["apps"].setdefault(k, {})
        settings["apps"][k].setdefault("allowed_roles", v["allowed_roles"][:])
    return settings

def load_settings() -> Dict[str, Any]:
    try:
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            content = r.json()
            raw = base64.b64decode(content["content"]).decode()
            data = json.loads(raw) if raw.strip() else DEFAULT_SETTINGS.copy()
            return _ensure_shape(data)
        # 404 or other → create default
        save_settings(DEFAULT_SETTINGS.copy())
        return _ensure_shape(DEFAULT_SETTINGS.copy())
    except Exception:
        # fallback
        return _ensure_shape(DEFAULT_SETTINGS.copy())

def save_settings(settings: Dict[str, Any]) -> None:
    settings = _ensure_shape(settings)
    try:
        # get sha if exists
        sha = None
        r = requests.get(_gh_url(), headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")

        payload = {
            "message": "Update pilot settings",
            "content": base64.b64encode(json.dumps(settings, indent=2).encode()).decode()
        }
        if sha:
            payload["sha"] = sha

        requests.put(_gh_url(), headers=HEADERS, json=payload, timeout=10)
    except Exception:
        pass

def has_global_access(member) -> bool:
    # server owner always allowed
    try:
        if member.guild and member.guild.owner_id == member.id:
            return True
    except Exception:
        pass

    # override role always allowed
    if any(getattr(r, "id", None) == OVERRIDE_ROLE_ID for r in getattr(member, "roles", [])):
        return True

    settings = load_settings()
    allowed = set(settings.get("global_allowed_roles", []))
    member_roles = {r.id for r in getattr(member, "roles", [])}
    return bool(member_roles & allowed)

def has_app_access(member, app_key: str) -> bool:
    if has_global_access(member):
        return True
    settings = load_settings()
    app = settings.get("apps", {}).get(app_key, {})
    allowed = set(app.get("allowed_roles", []))
    member_roles = {r.id for r in getattr(member, "roles", [])}
    return bool(member_roles & allowed)
