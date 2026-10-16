"""
Reporting App - Modern Windows Setup & Installer Wizard
=======================================================
A standalone installer wizard that installs Reporting App by Avi into
%LOCALAPPDATA%\\Programs\\GitHubWorkReporter, creates Desktop & Start Menu shortcuts,
and registers the app in Windows Add/Remove Programs.
"""

import os
import sys
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk

from app_config import APP_VERSION, APP_NAME
import app_installer

# Ensure stdout/stderr/stdin are safe
class NullWriter:
    def write(self, s): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None: sys.stdout = NullWriter()
if sys.stderr is None: sys.stderr = NullWriter()

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class SetupWizardApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Reporting App by Avi - Setup Wizard")
        self.geometry("520x460")
        self.resizable(False, False)

        # Set window icon if available
        icon_path = self._get_resource_path("app_icon.ico")
        if os.path.isfile(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.install_dir = app_installer.get_install_dir()
        self.is_installing = False

        self._build_ui()

    def _get_resource_path(self, relative_path: str) -> str:
        """Get absolute path to resource, works for dev and for PyInstaller _MEIPASS."""
        base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, relative_path)

    def _build_ui(self):
        # Header banner
        header = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=0, height=80)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", padx=24, pady=16)

        ctk.CTkLabel(title_box, text="📊", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 12))

        labels_box = ctk.CTkFrame(title_box, fg_color="transparent")
        labels_box.pack(side="left")

        ctk.CTkLabel(
            labels_box,
            text="Reporting App by Avi",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w")

        ctk.CTkLabel(
            labels_box,
            text=f"Version {APP_VERSION} Installation Wizard",
            font=ctk.CTkFont(size=12),
            text_color="#94a3b8"
        ).pack(anchor="w")

        # Main Content Card
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=24, pady=16)

        ctk.CTkLabel(
            content,
            text="This wizard will install Reporting App on your computer.",
            font=ctk.CTkFont(size=13),
            text_color="#e2e8f0"
        ).pack(anchor="w", pady=(0, 12))

        # Destination card
        dest_card = ctk.CTkFrame(content, corner_radius=8, fg_color="#1e293b")
        dest_card.pack(fill="x", pady=(0, 14))

        ctk.CTkLabel(
            dest_card,
            text="Installation Folder:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self.lbl_path = ctk.CTkLabel(
            dest_card,
            text=self.install_dir,
            font=ctk.CTkFont(size=11),
            text_color="#38bdf8",
            wraplength=460,
            justify="left"
        )
        self.lbl_path.pack(anchor="w", padx=16, pady=(0, 12))

        # Options card
        options_card = ctk.CTkFrame(content, corner_radius=8, fg_color="#1e293b")
        options_card.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            options_card,
            text="Shortcuts & Preferences:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        self.cb_desktop = ctk.CTkCheckBox(
            options_card,
            text="Create a Desktop Shortcut (Open directly from your Desktop)",
            font=ctk.CTkFont(size=12)
        )
        self.cb_desktop.select()
        self.cb_desktop.pack(anchor="w", padx=16, pady=(0, 6))

        self.cb_start_menu = ctk.CTkCheckBox(
            options_card,
            text="Add to Windows Start Menu (Searchable in Windows Search)",
            font=ctk.CTkFont(size=12)
        )
        self.cb_start_menu.select()
        self.cb_start_menu.pack(anchor="w", padx=16, pady=(0, 6))

        self.cb_launch = ctk.CTkCheckBox(
            options_card,
            text="Launch Reporting App immediately after installation",
            font=ctk.CTkFont(size=12)
        )
        self.cb_launch.select()
        self.cb_launch.pack(anchor="w", padx=16, pady=(0, 14))

        # Status and Progress Bar
        self.progress_bar = ctk.CTkProgressBar(content, mode="indeterminate", height=6)
        self.lbl_status = ctk.CTkLabel(content, text="Ready to install.", font=ctk.CTkFont(size=12), text_color="#94a3b8")
        self.lbl_status.pack(anchor="w", pady=(0, 8))

        # Bottom Buttons
        btn_box = ctk.CTkFrame(content, fg_color="transparent")
        btn_box.pack(fill="x", side="bottom")

        self.btn_install = ctk.CTkButton(
            btn_box,
            text="🚀 Install Now",
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#059669",
            hover_color="#047857",
            command=self.start_installation
        )
        self.btn_install.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_cancel = ctk.CTkButton(
            btn_box,
            text="Cancel",
            height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#334155",
            hover_color="#475569",
            command=self.destroy
        )
        self.btn_cancel.pack(side="right", padx=(8, 0))

    def start_installation(self):
        if self.is_installing:
            return

        self.is_installing = True
        self.btn_install.configure(state="disabled", text="Installing...")
        self.btn_cancel.configure(state="disabled")
        self.progress_bar.pack(fill="x", pady=(0, 6))
        self.progress_bar.start()
        self.lbl_status.configure(text="Installing application files to your PC...", text_color="#38bdf8")

        threading.Thread(target=self._run_install_worker, daemon=True).start()

    def _run_install_worker(self):
        try:
            # Terminate any running instance of GitHubWorkReporter.exe before overwriting
            if sys.platform == "win32":
                try:
                    subprocess.run(["taskkill", "/f", "/im", "GitHubWorkReporter.exe"], capture_output=True, check=False)
                except Exception:
                    pass

            target_exe = app_installer.get_installed_exe_path()
            install_dir = app_installer.get_install_dir()

            # Locate the source executable to install
            # 1. Check embedded in PyInstaller bundle (_MEIPASS)
            # 2. Check local dist/ folder or alongside installer
            source_candidates = [
                self._get_resource_path("GitHubWorkReporter.exe"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "GitHubWorkReporter.exe"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "GitHubWorkReporter.exe"),
            ]
            source_exe = None
            for cand in source_candidates:
                if os.path.isfile(cand):
                    source_exe = cand
                    break

            if not source_exe:
                raise FileNotFoundError("Could not locate GitHubWorkReporter.exe package to install.")

            # Copy executable
            shutil.copy2(source_exe, target_exe)

            # Copy icon if available
            icon_source = self._get_resource_path("app_icon.ico")
            if os.path.isfile(icon_source):
                try:
                    shutil.copy2(icon_source, os.path.join(install_dir, "app_icon.ico"))
                except Exception:
                    pass

            # Create uninstaller
            app_installer.create_uninstaller_script(install_dir)

            # Register in Windows Add/Remove Programs
            app_installer.register_in_add_remove_programs(install_dir, target_exe, APP_VERSION)

            # Setup shortcuts according to user choice
            if self.cb_desktop.get():
                user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
                desktop_lnk = os.path.join(user_profile, "Desktop", f"{app_installer.APP_DISPLAY_NAME}.lnk")
                app_installer.create_windows_shortcut(target_exe, desktop_lnk, app_installer.APP_DISPLAY_NAME)

            if self.cb_start_menu.get():
                app_data = os.environ.get("APPDATA", os.path.expanduser(r"~\AppData\Roaming"))
                start_dir = os.path.join(app_data, "Microsoft", "Windows", "Start Menu", "Programs")
                start_lnk = os.path.join(start_dir, f"{app_installer.APP_DISPLAY_NAME}.lnk")
                app_installer.create_windows_shortcut(target_exe, start_lnk, app_installer.APP_DISPLAY_NAME)

            self.after(0, self._on_install_success, target_exe)
        except Exception as err:
            self.after(0, self._on_install_error, str(err))

    def _on_install_success(self, target_exe: str):
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.lbl_status.configure(text="✔ Installation completed successfully!", text_color="#34d399")

        should_launch = bool(self.cb_launch.get())
        if should_launch and os.path.isfile(target_exe):
            try:
                # Remove PyInstaller parent temp directory from environment
                # so the child executable runs in its own independent runtime
                clean_env = os.environ.copy()
                clean_env.pop("_MEIPASS2", None)
                clean_env.pop("_MEIPASS", None)
                os.environ.pop("_MEIPASS2", None)
                os.environ.pop("_MEIPASS", None)

                if hasattr(os, "startfile"):
                    os.startfile(target_exe)
                else:
                    subprocess.Popen(
                        [target_exe],
                        cwd=os.path.dirname(target_exe),
                        env=clean_env,
                        close_fds=True,
                        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                    )
            except Exception:
                pass

        messagebox.showinfo(
            "Installation Complete",
            f"Reporting App by Avi (v{APP_VERSION}) has been successfully installed!\n\n"
            "A Desktop shortcut and Start Menu entry have been created.\n"
            "You can now launch the app anytime from your Desktop or Start Menu."
        )
        self.destroy()

    def _on_install_error(self, err_msg: str):
        self.is_installing = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.btn_install.configure(state="normal", text="🚀 Try Again")
        self.btn_cancel.configure(state="normal")
        self.lbl_status.configure(text=f"Error: {err_msg}", text_color="#ef4444")
        messagebox.showerror("Installation Error", f"Failed to complete installation:\n\n{err_msg}")


def main():
    app = SetupWizardApp()
    app.mainloop()


if __name__ == "__main__":
    main()
