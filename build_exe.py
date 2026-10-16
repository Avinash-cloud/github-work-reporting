"""
GitHub Work Reporter - PyInstaller Packaging Automation
=======================================================
Bundles the GUI application into a single portable Windows executable (.exe)
that requires zero external dependencies or Python installation.
"""

import os
import sys
import subprocess
import shutil

try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def build():
    print("=" * 70)
    print("🚀 BUNDLING GITHUB WORK REPORTER INTO STANDALONE .EXE")
    print("=" * 70)

    project_dir = os.path.dirname(os.path.abspath(__file__))
    dist_dir = os.path.join(project_dir, "dist")
    build_dir = os.path.join(project_dir, "build")

    # If GitHubWorkReporter processes are currently running, terminate them so Windows doesn't lock files
    if sys.platform == "win32":
        try:
            subprocess.run(["taskkill", "/f", "/im", "GitHubWorkReporter.exe"], capture_output=True, check=False)
            subprocess.run(["taskkill", "/f", "/im", "GitHubWorkReporter_Setup.exe"], capture_output=True, check=False)
        except Exception:
            pass

    icon_file = os.path.join(project_dir, "app_icon.ico")
    icon_arg = [f"--icon={icon_file}"] if os.path.isfile(icon_file) else []
    icon_data = [f"--add-data={icon_file};."] if os.path.isfile(icon_file) else []

    # -----------------------------------------------------------------------
    # Step 1: Build the Main Application Executable (GitHubWorkReporter.exe)
    # -----------------------------------------------------------------------
    print("\n[1/2] Building Main Application Executable (GitHubWorkReporter.exe)...")
    cmd_app = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=GitHubWorkReporter",
        "--onefile",
        "--windowed",
        *icon_arg,
        *icon_data,
        "--collect-all", "customtkinter",
        "--clean",
        os.path.join(project_dir, "main.py")
    ]

    res_app = subprocess.run(cmd_app, cwd=project_dir, check=False)
    if res_app.returncode != 0:
        print("\n❌ PyInstaller build failed for main application with exit code:", res_app.returncode)
        sys.exit(res_app.returncode)

    app_exe = os.path.join(dist_dir, "GitHubWorkReporter.exe")
    if not os.path.isfile(app_exe):
        print(f"\n❌ Expected output executable not found at: {app_exe}")
        sys.exit(1)

    app_size_mb = os.path.getsize(app_exe) / (1024 * 1024)
    print(f"✔ Main executable built: {app_exe} ({app_size_mb:.2f} MB)")

    # -----------------------------------------------------------------------
    # Step 2: Build the Windows Setup Wizard (GitHubWorkReporter_Setup.exe)
    # -----------------------------------------------------------------------
    print("\n[2/2] Building Windows Installer Wizard (GitHubWorkReporter_Setup.exe)...")
    cmd_setup = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=GitHubWorkReporter_Setup",
        "--onefile",
        "--windowed",
        *icon_arg,
        *icon_data,
        f"--add-data={app_exe};.",
        "--collect-all", "customtkinter",
        os.path.join(project_dir, "setup_gui.py")
    ]

    res_setup = subprocess.run(cmd_setup, cwd=project_dir, check=False)
    if res_setup.returncode != 0:
        print("\n❌ PyInstaller build failed for setup installer with exit code:", res_setup.returncode)
        sys.exit(res_setup.returncode)

    setup_exe = os.path.join(dist_dir, "GitHubWorkReporter_Setup.exe")
    setup_size_mb = os.path.getsize(setup_exe) / (1024 * 1024) if os.path.isfile(setup_exe) else 0

    print("\n" + "=" * 70)
    print("✔ ALL BUILDS SUCCEEDED!")
    print(f"📦 1. Main Executable:   {app_exe} ({app_size_mb:.2f} MB)")
    if os.path.isfile(setup_exe):
        print(f"💿 2. Windows Installer: {setup_exe} ({setup_size_mb:.2f} MB)")
    print("=" * 70)
    print("\nShare with users:")
    print("  • GitHubWorkReporter_Setup.exe -> One-click installer (creates Desktop & Start Menu icons)")
    print("  • GitHubWorkReporter.exe       -> Standalone portable version\n")

if __name__ == "__main__":
    build()
