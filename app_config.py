"""
GitHub Work Reporter - Configuration Manager
============================================
Handles persistent user preferences and credentials stored in standard
Windows application data (%APPDATA%/GitHubWorkReporter/config.json).
"""

import os
import json
from typing import Any, Dict

APP_NAME = "GitHubWorkReporter"
DEFAULT_GITHUB_REPO = "Avinash-cloud/github-work-reporting"
APP_VERSION = "1.1.0"


def get_app_data_dir() -> str:
    """Returns the platform-appropriate app data directory path."""
    app_data = os.environ.get("APPDATA")
    if not app_data:
        app_data = os.path.expanduser("~")
    base_dir = os.path.join(app_data, APP_NAME)
    os.makedirs(base_dir, exist_ok=True)
    return base_dir


def get_config_file_path() -> str:
    return os.path.join(get_app_data_dir(), "config.json")


def get_default_reports_dir() -> str:
    """Returns default reports output directory."""
    # First priority: reports/ in current working directory if available
    cwd_reports = os.path.join(os.getcwd(), "reports")
    try:
        os.makedirs(cwd_reports, exist_ok=True)
        return cwd_reports
    except Exception:
        pass
    # Fallback: reports/ in %APPDATA%
    user_reports = os.path.join(get_app_data_dir(), "reports")
    os.makedirs(user_reports, exist_ok=True)
    return user_reports


class ConfigManager:
    """Manages reading and writing application configuration."""

    DEFAULT_CONFIG = {
        "token": "",
        "remember_token": True,
        "github_update_repo": DEFAULT_GITHUB_REPO,
        "skip_merges": True,
        "include_stats": False,
        "theme": "Dark",
        "last_author": "",
        "cached_user": {},
        "output_dir": ""
    }

    def __init__(self):
        self.file_path = get_config_file_path()
        self.config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        data = dict(self.DEFAULT_CONFIG)
        # Check if local .env has a token fallback
        token_env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token_env:
            data["token"] = token_env.strip()

        if os.path.isfile(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data.update(loaded)
            except Exception:
                pass
        return data

    def save(self) -> bool:
        """Saves current configuration to disk."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any, auto_save: bool = True):
        self.config[key] = value
        if auto_save:
            self.save()

    def clear_token(self):
        self.config["token"] = ""
        self.config["cached_user"] = {}
        self.save()
