"""
GitHub Work Reporter - Application Auto-Updater
================================================
Checks for updates against GitHub Releases, downloads release binaries,
and safely updates the executable on Windows.
"""

import os
import sys
import io
import json
import re
import tempfile
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Tuple, Dict, Any, Callable

# Ensure stdout/stderr/stdin are never None (essential for PyInstaller --windowed mode)
class NullWriter(io.TextIOBase):
    def write(self, s): return len(s) if s else 0
    def flush(self): pass
    def isatty(self): return False
    def readable(self): return False
    def writable(self): return True
    def seekable(self): return False
    @property
    def encoding(self): return "utf-8"

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()
if sys.stdin is None:
    sys.stdin = io.StringIO()
if getattr(sys, "__stdout__", None) is None:
    sys.__stdout__ = sys.stdout
if getattr(sys, "__stderr__", None) is None:
    sys.__stderr__ = sys.stderr
if getattr(sys, "__stdin__", None) is None:
    sys.__stdin__ = sys.stdin

from app_config import APP_VERSION, DEFAULT_GITHUB_REPO


def parse_semver(v_str: str) -> Tuple[int, int, int]:
    """Parses a version tag like 'v1.2.3' or '1.2' into a tuple (major, minor, patch)."""
    cleaned = re.sub(r"^[^0-9]*", "", v_str.strip())
    parts = cleaned.split(".")
    major = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else 0
    minor = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    patch = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    return major, minor, patch


def is_version_newer(latest_tag: str, current_version: str) -> bool:
    """Returns True if latest_tag is strictly newer than current_version."""
    try:
        latest = parse_semver(latest_tag)
        current = parse_semver(current_version)
        return latest > current
    except Exception:
        return False


class UpdateManager:
    """Handles checking, downloading, and applying application updates from GitHub."""

    def __init__(self, repo_full_name: str = DEFAULT_GITHUB_REPO, current_version: str = APP_VERSION, token: Optional[str] = None):
        self.repo = repo_full_name.strip()
        self.current_version = current_version
        self.token = token.strip() if token else None

    def check_for_updates(self) -> Dict[str, Any]:
        """
        Queries GitHub API for the latest release.
        Returns dict with keys:
          'has_update': bool,
          'latest_version': str,
          'release_title': str,
          'release_notes': str,
          'published_at': str,
          'asset_name': Optional[str],
          'asset_url': Optional[str],
          'asset_size': int,
          'html_url': str,
          'error': Optional[str]
        """
        api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(api_url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "GitHub-Work-Reporter-Updater")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return {
                    "has_update": False,
                    "latest_version": self.current_version,
                    "error": None,
                    "up_to_date": True,
                    "message": "You are on the latest version. No updates are currently available."
                }
            return {
                "has_update": False,
                "latest_version": self.current_version,
                "error": f"GitHub API error ({err.code}): {err.reason}"
            }
        except Exception as err:
            return {
                "has_update": False,
                "latest_version": self.current_version,
                "error": f"Connection error checking for updates: {err}"
            }

        tag_name = data.get("tag_name", "")
        has_update = is_version_newer(tag_name, self.current_version)

        # Look for executable asset (.exe)
        exe_asset = None
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.lower().endswith(".exe"):
                exe_asset = asset
                break

        return {
            "has_update": has_update,
            "latest_version": tag_name,
            "release_title": data.get("name") or tag_name,
            "release_notes": data.get("body", "No release notes provided."),
            "published_at": (data.get("published_at") or "")[:10],
            "asset_name": exe_asset.get("name") if exe_asset else None,
            "asset_url": exe_asset.get("browser_download_url") if exe_asset else None,
            "asset_size": exe_asset.get("size", 0) if exe_asset else 0,
            "html_url": data.get("html_url", f"https://github.com/{self.repo}/releases"),
            "error": None
        }

    def download_update(self, download_url: str, progress_callback: Optional[Callable[[int, int], None]] = None) -> str:
        """
        Downloads the updated executable to a temporary file.
        Invokes progress_callback(bytes_read, total_bytes) if provided.
        Returns the downloaded temporary file path.
        """
        req = urllib.request.Request(download_url)
        req.add_header("User-Agent", "GitHub-Work-Reporter-Updater")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, "GitHubWorkReporter_update.exe")

        with urllib.request.urlopen(req, timeout=60) as resp, open(temp_file_path, "wb") as out_f:
            total_size = int(resp.headers.get("content-length", 0))
            bytes_read = 0
            chunk_size = 64 * 1024

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                bytes_read += len(chunk)
                if progress_callback:
                    progress_callback(bytes_read, total_size)

        return temp_file_path

    @staticmethod
    def apply_update_and_restart(new_exe_path: str) -> bool:
        """
        Replaces the current executable with the downloaded update and relaunches.
        Uses a helper batch script on Windows so file locks are released cleanly.
        """
        is_frozen = getattr(sys, "frozen", False)
        current_exe = sys.executable if is_frozen else None

        if not current_exe or not os.path.isfile(current_exe):
            # Running directly from Python source code, can't self-replace Python interpreter
            return False

        temp_dir = tempfile.gettempdir()
        batch_script_path = os.path.join(temp_dir, "gh_reporter_updater.bat")

        # Windows batch script: waits for current app to exit, overwrites exe, and relaunches
        batch_script_content = f"""@echo off
setlocal
set _MEIPASS2=
set _MEIPASS=
echo Waiting for application to close...
timeout /t 2 /nobreak >nul

:RETRY_LOOP
copy /y "{new_exe_path}" "{current_exe}" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto RETRY_LOOP
)
del /f /q "{new_exe_path}" 2>nul

echo Update applied successfully! Starting new version...
start "" "{current_exe}"
del "%~f0"
exit
"""

        with open(batch_script_path, "w", encoding="utf-8") as f:
            f.write(batch_script_content)

        # Launch the batch script detached from this process with clean environment
        clean_env = os.environ.copy()
        clean_env.pop("_MEIPASS2", None)
        clean_env.pop("_MEIPASS", None)
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            ["cmd.exe", "/c", batch_script_path],
            env=clean_env,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True
        )

        # Terminate current app cleanly
        sys.exit(0)
        return True
