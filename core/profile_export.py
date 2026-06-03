from datetime import datetime, timezone
from typing import Any, Dict, Optional


def build_extension_profile_payload(
    profile: Dict[str, Any],
    workday_credentials: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the explicit import payload consumed by the Chrome extension."""
    payload_profile = dict(profile)
    credentials = workday_credentials or payload_profile.get("workday_credentials", {}) or {}
    payload_profile["workday_credentials"] = credentials

    return {
        "schema_version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "intern-bot-desktop",
        "profile": payload_profile,
        "workday_credentials": credentials,
    }
