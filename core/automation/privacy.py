"""Disable third-party telemetry and cloud sync for every automation dependency."""
import os


def configure_privacy():
    os.environ["ANONYMIZED_TELEMETRY"] = "false"
    os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
    os.environ["DO_NOT_TRACK"] = "1"
