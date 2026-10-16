"""
GitHub Work Reporter - Windows Application Installer & Shortcut Manager
======================================================================
Installs the application into the standard Windows per-user directory
(%LOCALAPPDATA%\\Programs\\GitHubWorkReporter), creates Desktop and Start Menu
shortcuts, and registers the app in Windows Add/Remove Programs.
"""

import os
import sys
import shutil
import subprocess
import winreg
from typing import Dict, Optional, Tuple

from app_config import APP_VERSION, APP_NAME

APP_DISPLAY_NAME = "Reporting App by Avi"
APP_EXE_NAME = "GitHubWorkReporter.exe"


def get_install_dir() -> str:
    """Returns the standard Windows per-user installation directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = os.path.expanduser(r"~\AppData\Local")
    install_dir = os.path.join(local_app_data, "Programs", APP_NAME)
    os.makedirs(install_dir, exist_ok=True)
    return install_dir


def get_installed_exe_path() -> str:
    """Returns the expected path of the installed executable."""
    return os.path.join(get_install_dir(), APP_EXE_NAME)


def is_running_installed() -> bool:
    """Returns True if the currently running executable is inside the installed folder."""
    is_frozen = getattr(sys, "frozen", False)
    if not is_frozen:
        return False
    current_exe = os.path.abspath(sys.executable).lower()
    installed_exe = os.path.abspath(get_installed_exe_path()).lower()
    return current_exe == installed_exe


def create_windows_shortcut(target_exe: str, shortcut_path: str, name: str = APP_DISPLAY_NAME, icon_path: Optional[str] = None) -> bool:
    """
    Creates a Windows .lnk shortcut using WScript.Shell via PowerShell.
    Zero external pip dependencies required.
    """
    try:
        target_abs = os.path.abspath(target_exe).replace("'", "''")
        shortcut_abs = os.path.abspath(shortcut_path).replace("'", "''")
        work_dir = os.path.dirname(os.path.abspath(target_exe)).replace("'", "''")
        icon = (icon_path or target_exe).replace("'", "''")

        ps_script = (
            f"$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut('{shortcut_abs}'); "
            f"$s.TargetPath = '{target_abs}'; "
            f"$s.WorkingDirectory = '{work_dir}'; "
            f"$s.Description = '{name}'; "
            f"$s.IconLocation = '{icon},0'; "
            f"$s.Save()"
        )

        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
        return res.returncode == 0 and os.path.isfile(shortcut_path)
    except Exception:
        return False


def setup_desktop_and_start_menu_shortcuts(target_exe: Optional[str] = None) -> Dict[str, bool]:
    """
    Creates both Desktop and Start Menu shortcuts pointing to the target executable.
    Defaults to the installed executable.
    """
    exe_path = target_exe or get_installed_exe_path()
    results = {"desktop": False, "start_menu": False}

    if not os.path.isfile(exe_path):
        return results

    # Desktop shortcut
    user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    desktop_dir = os.path.join(user_profile, "Desktop")
    if os.path.isdir(desktop_dir):
        desktop_link = os.path.join(desktop_dir, f"{APP_DISPLAY_NAME}.lnk")
        results["desktop"] = create_windows_shortcut(exe_path, desktop_link, APP_DISPLAY_NAME)

    # Start Menu shortcut
    app_data = os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))
    start_menu_dir = os.path.join(app_data, "Microsoft", "Windows", "Start Menu", "Programs")
    if os.path.isdir(start_menu_dir):
        start_link = os.path.join(start_menu_dir, f"{APP_DISPLAY_NAME}.lnk")
        results["start_menu"] = create_windows_shortcut(exe_path, start_link, APP_DISPLAY_NAME)

    return results


def register_in_add_remove_programs(install_dir: str, target_exe: str, version: str = APP_VERSION):
    """
    Registers the application in Windows Current User Uninstall registry
    so it appears in Windows Settings -> Installed Apps / Add or Remove Programs.
    """
    try:
        key_path = fr"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_DISPLAY_NAME)
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Avinash Cloud")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f"{target_exe},0")
            uninstaller_bat = os.path.join(install_dir, "uninstall.bat")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_bat}"')
    except Exception:
        pass


def create_uninstaller_script(install_dir: str):
    """Creates a simple, reliable uninstaller batch script inside the installation directory."""
    uninstaller_path = os.path.join(install_dir, "uninstall.bat")
    content = f"""@echo off
title Uninstalling {APP_DISPLAY_NAME}
echo Removing {APP_DISPLAY_NAME}...

:: Remove shortcuts
del "%USERPROFILE%\\Desktop\\{APP_DISPLAY_NAME}.lnk" 2>nul
del "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_DISPLAY_NAME}.lnk" 2>nul

:: Remove registry entry
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_NAME}" /f 2>nul

echo {APP_DISPLAY_NAME} has been uninstalled.
echo You can now delete this folder if you wish.
timeout /t 3 >nul
"""
    try:
        with open(uninstaller_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        pass


def install_application(source_exe_path: str) -> Tuple[bool, str]:
    """
    Copies source_exe_path to %LOCALAPPDATA%\\Programs\\GitHubWorkReporter\\GitHubWorkReporter.exe,
    creates Desktop & Start Menu shortcuts, registers in Windows, and returns (success, installed_exe_path).
    """
    try:
        install_dir = get_install_dir()
        target_exe = os.path.join(install_dir, APP_EXE_NAME)

        # Copy executable
        if os.path.abspath(source_exe_path).lower() != os.path.abspath(target_exe).lower():
            shutil.copy2(source_exe_path, target_exe)

        # Copy app_icon.ico if present
        source_dir = os.path.dirname(os.path.abspath(source_exe_path))
        local_icon = os.path.join(source_dir, "app_icon.ico")
        target_icon = os.path.join(install_dir, "app_icon.ico")
        if os.path.isfile(local_icon) and not os.path.isfile(target_icon):
            try:
                shutil.copy2(local_icon, target_icon)
            except Exception:
                pass

        # Create uninstaller
        create_uninstaller_script(install_dir)

        # Register in Windows Add/Remove Programs
        register_in_add_remove_programs(install_dir, target_exe, APP_VERSION)

        # Setup shortcuts
        setup_desktop_and_start_menu_shortcuts(target_exe)

        return True, target_exe
    except Exception as err:
        return False, str(err)
