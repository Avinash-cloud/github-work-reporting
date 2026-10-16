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

    # Command arguments for PyInstaller
    cmd = [
        sys.executable,
        "-m", "PyInstaller",
        "--name=GitHubWorkReporter",
        "--onefile",
        "--windowed",
        "--collect-all", "customtkinter",
        "--clean",
        os.path.join(project_dir, "main.py")
    ]

    print("\nRunning command:")
    print(" ".join(cmd))
    print("\nCompiling... (this may take 1-2 minutes)\n")

    res = subprocess.run(cmd, cwd=project_dir, check=False)
    if res.returncode != 0:
        print("\n❌ PyInstaller build failed with exit code:", res.returncode)
        sys.exit(res.returncode)

    output_exe = os.path.join(dist_dir, "GitHubWorkReporter.exe")
    if os.path.isfile(output_exe):
        size_mb = os.path.getsize(output_exe) / (1024 * 1024)
        print("\n" + "=" * 70)
        print("✔ BUILD SUCCEEDED!")
        print(f"📦 Standalone Executable: {output_exe}")
        print(f"⚖️  File Size:             {size_mb:.2f} MB")
        print("=" * 70)
        print("\nYou can now share 'GitHubWorkReporter.exe' with any Windows user!")
        print("They do NOT need Python, Git, or anything installed to run it.\n")
    else:
        print(f"\n❌ Expected output executable not found at: {output_exe}")
        sys.exit(1)

if __name__ == "__main__":
    build()
