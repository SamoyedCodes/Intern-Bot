"""Cloud recovery remains unavailable until a sanitized observation adapter is audited."""
import os


def configure_privacy():
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
    os.environ["DO_NOT_TRACK"] = "1"


class BoundedRecovery:
    """Explicit, fail-closed boundary. Never construct an unrestricted Browser Use agent.

    Browser Use automatically assembles browser observations, including filled values.
    Its sensitive_data parameter is insufficient for the approved privacy boundary.
    The optional pinned dependency is reserved for a reviewed sanitized adapter.
    """
    enabled = False
    reason = "AI recovery is disabled: sanitized browser observations have not passed the privacy gate."

    async def recover(self, *args, **kwargs):
        configure_privacy()
        return False
