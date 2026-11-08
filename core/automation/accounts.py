"""Per-employer login addresses; 1Password generates the passwords."""
import re

DEFAULT_CATCHALL_FORMAT = "{company}_intern"


def login_address(site: str, email: str, catchall: str = "", catchall_format: str = "") -> str:
    domain = catchall.strip().lstrip("@")
    if not domain:
        if not email or "@" not in email:
            raise ValueError("An email is required")
        return email
    if any(c.isspace() for c in domain) or "/" in domain or "@" in domain or "." not in domain:
        raise ValueError("Invalid catch-all domain")
    local = (catchall_format.strip() or DEFAULT_CATCHALL_FORMAT).replace("{company}", site.split(".")[0].replace("-", "_"))
    if not re.fullmatch(r"[A-Za-z0-9_+-](?:[A-Za-z0-9._+-]{0,62}[A-Za-z0-9_+-])?", local) or ".." in local:
        raise ValueError("Invalid catch-all address format")
    return local + "@" + domain

