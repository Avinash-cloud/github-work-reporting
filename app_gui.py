"""
GitHub Work Reporter - Modern Desktop GUI Application
=====================================================
A native Windows desktop application built with CustomTkinter.
Features:
- GitHub Token authentication and live connection status.
- Day-wise, categorized reporting across public and private repositories.
- Multi-format generation (PDF, HTML, Text doc, Markdown).
- Automatic GitHub Releases update checker and self-installer.
"""

import os
import sys
import io
import threading
import webbrowser
import calendar
from datetime import date, datetime, timedelta
from typing import Optional
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

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

# Local module imports
from app_config import ConfigManager, APP_VERSION, DEFAULT_GITHUB_REPO, get_default_reports_dir
from app_updater import UpdateManager
from reportingscript import (
    GitHubClient,
    WorkCollector,
    ReportGenerator,
    resolve_date_range,
    parse_date_str,
    find_browser_for_pdf
)

# Configure default appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# ---------------------------------------------------------------------------
# Calendar Date Picker Popup Widget
# ---------------------------------------------------------------------------
class CTkDatePicker(ctk.CTkToplevel):
    """
    Interactive Dark-Themed Calendar Date Picker modal dialog.
    Allows easy month/year navigation, quick 'Today' jump, and click-to-select.
    """
    def __init__(self, parent, target_entry: ctk.CTkEntry, initial_date: Optional[date] = None, title: str = "Select Date"):
        super().__init__(parent)
        self.target_entry = target_entry
        self.title(title)
        self.geometry("340x380")
        self.resizable(False, False)
        self.transient(parent)

        sel_date = None
        if target_entry:
            val = target_entry.get().strip()
            try:
                sel_date = datetime.strptime(val, "%Y-%m-%d").date()
            except Exception:
                pass

        self.selected_date = sel_date or initial_date or date.today()
        self.today = date.today()
        self.view_year = self.selected_date.year
        self.view_month = self.selected_date.month

        self._position_popup(target_entry)
        self._build_ui()

        self.grab_set()
        self.focus_set()
        self.bind("<Escape>", lambda e: self.destroy())

    def _position_popup(self, widget):
        self.update_idletasks()
        try:
            if widget:
                widget.update_idletasks()
                x = widget.winfo_rootx()
                y = widget.winfo_rooty() + widget.winfo_height() + 6
                screen_w = self.winfo_screenwidth()
                screen_h = self.winfo_screenheight()
                w, h = 340, 380
                if x + w > screen_w:
                    x = max(10, screen_w - w - 20)
                if y + h > screen_h:
                    y = max(10, widget.winfo_rooty() - h - 10)
                self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            self.geometry("340x380")

    def _build_ui(self):
        # Header navigation: Prev Year, Prev Month, Month & Year, Next Month, Next Year
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkButton(
            header_frame, text="«", width=28, height=28, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#334155", hover_color="#475569", command=self._prev_year
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            header_frame, text="‹", width=28, height=28, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#334155", hover_color="#475569", command=self._prev_month
        ).pack(side="left", padx=2)

        self.lbl_month_year = ctk.CTkLabel(
            header_frame,
            text=f"{calendar.month_name[self.view_month]} {self.view_year}",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f8fafc"
        )
        self.lbl_month_year.pack(side="left", expand=True)

        ctk.CTkButton(
            header_frame, text="›", width=28, height=28, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#334155", hover_color="#475569", command=self._next_month
        ).pack(side="right", padx=2)

        ctk.CTkButton(
            header_frame, text="»", width=28, height=28, font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#334155", hover_color="#475569", command=self._next_year
        ).pack(side="right", padx=2)

        # Days of week header
        weekdays_frame = ctk.CTkFrame(self, fg_color="transparent")
        weekdays_frame.pack(fill="x", padx=14, pady=(4, 4))
        for d in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
            lbl = ctk.CTkLabel(
                weekdays_frame, text=d, font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#94a3b8", width=38
            )
            lbl.pack(side="left", expand=True)

        # Calendar days grid
        self.days_frame = ctk.CTkFrame(self, fg_color="#1e293b", corner_radius=6)
        self.days_frame.pack(fill="both", expand=True, padx=14, pady=4)

        self._render_days()

        # Bottom Action Bar
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=14, pady=(6, 12))

        ctk.CTkButton(
            bottom_frame, text="Today", width=70, height=28, font=ctk.CTkFont(size=11),
            fg_color="#334155", hover_color="#475569", command=self._select_today
        ).pack(side="left")

        ctk.CTkButton(
            bottom_frame, text="Close", width=70, height=28, font=ctk.CTkFont(size=11),
            fg_color="#475569", hover_color="#64748b", command=self.destroy
        ).pack(side="right")

    def _render_days(self):
        for w in self.days_frame.winfo_children():
            w.destroy()

        self.lbl_month_year.configure(text=f"{calendar.month_name[self.view_month]} {self.view_year}")
        weeks = calendar.monthcalendar(self.view_year, self.view_month)

        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                if day == 0:
                    lbl = ctk.CTkLabel(self.days_frame, text="", width=38, height=30)
                    lbl.grid(row=r, column=c, padx=2, pady=2)
                else:
                    is_selected = (
                        self.selected_date and
                        self.selected_date.year == self.view_year and
                        self.selected_date.month == self.view_month and
                        self.selected_date.day == day
                    )
                    is_today = (
                        self.today.year == self.view_year and
                        self.today.month == self.view_month and
                        self.today.day == day
                    )

                    fg = "#2563eb" if is_selected else ("#0f766e" if is_today else "#0f172a")
                    hover = "#1d4ed8" if is_selected else "#334155"
                    border_w = 1 if is_today and not is_selected else 0
                    border_c = "#38bdf8" if is_today and not is_selected else None

                    btn = ctk.CTkButton(
                        self.days_frame,
                        text=str(day),
                        width=38,
                        height=30,
                        font=ctk.CTkFont(size=12, weight="bold" if (is_selected or is_today) else "normal"),
                        fg_color=fg,
                        hover_color=hover,
                        border_width=border_w,
                        border_color=border_c,
                        corner_radius=4,
                        command=lambda d=day: self._select_day(d)
                    )
                    btn.grid(row=r, column=c, padx=2, pady=2)

    def _prev_month(self):
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self._render_days()

    def _next_month(self):
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self._render_days()

    def _prev_year(self):
        self.view_year -= 1
        self._render_days()

    def _next_year(self):
        self.view_year += 1
        self._render_days()

    def _select_day(self, day: int):
        chosen = date(self.view_year, self.view_month, day)
        if self.target_entry:
            self.target_entry.delete(0, "end")
            self.target_entry.insert(0, chosen.strftime("%Y-%m-%d"))
        self.destroy()

    def _select_today(self):
        self._select_day(self.today.day)


class WorkReporterApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Reporting App by Avi  v{APP_VERSION}")
        self.geometry("980x720")
        self.minsize(860, 600)

        self.config_mgr = ConfigManager()
        self.client: GitHubClient | None = None
        self.cached_repos: list[dict] = []
        self.last_generated_files: dict[str, str] = {}
        self.is_generating = False

        # Set window icon if available
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        icon_path = os.path.join(base_dir, "app_icon.ico")
        if os.path.isfile(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Build UI Structure
        self._build_header()
        self._build_tabs()

        # Attempt auto-connection if token is saved
        saved_token = self.config_mgr.get("token")
        if saved_token:
            self.token_entry.insert(0, saved_token)
            self.after(300, self.test_connection)

        # Auto-create Desktop shortcut on first run if missing
        if getattr(sys, "frozen", False):
            self.after(1000, self._auto_create_shortcuts_on_first_run)

    def _auto_create_shortcuts_on_first_run(self):
        try:
            import app_installer
            user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
            desktop_lnk = os.path.join(user_profile, "Desktop", f"{app_installer.APP_DISPLAY_NAME}.lnk")
            if not os.path.isfile(desktop_lnk):
                app_installer.setup_desktop_and_start_menu_shortcuts(sys.executable)
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Top Header
    # -----------------------------------------------------------------------
    def _build_header(self):
        header_frame = ctk.CTkFrame(self, fg_color="#0f172a", corner_radius=0, height=64)
        header_frame.pack(fill="x", side="top")
        header_frame.pack_propagate(False)

        # Title & Logo
        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", padx=20, pady=12)

        icon_label = ctk.CTkLabel(title_box, text="📊", font=ctk.CTkFont(size=24))
        icon_label.pack(side="left", padx=(0, 10))

        title_label = ctk.CTkLabel(
            title_box,
            text="GitHub Work Reporter",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#f8fafc"
        )
        title_label.pack(side="left")

        ver_badge = ctk.CTkLabel(
            title_box,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            text_color="#94a3b8",
            corner_radius=6,
            padx=8,
            pady=2
        )
        ver_badge.pack(side="left", padx=(10, 0))

        # Right Header: Connection Indicator & Theme Toggle
        right_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_box.pack(side="right", padx=20, pady=12)

        self.status_pill = ctk.CTkLabel(
            right_box,
            text="⚪ Disconnected",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#1e293b",
            text_color="#94a3b8",
            corner_radius=12,
            padx=12,
            pady=4
        )
        self.status_pill.pack(side="left", padx=(0, 12))

        self.theme_switch = ctk.CTkSwitch(
            right_box,
            text="Dark",
            font=ctk.CTkFont(size=12),
            command=self._toggle_theme,
            onvalue="Dark",
            offvalue="Light"
        )
        if self.config_mgr.get("theme") == "Light":
            self.theme_switch.deselect()
            ctk.set_appearance_mode("Light")
        else:
            self.theme_switch.select()
            ctk.set_appearance_mode("Dark")
        self.theme_switch.pack(side="left")

    def _toggle_theme(self):
        new_mode = "Dark" if self.theme_switch.get() == "Dark" else "Light"
        ctk.set_appearance_mode(new_mode)
        self.config_mgr.set("theme", new_mode)

    # -----------------------------------------------------------------------
    # Main Tabs
    # -----------------------------------------------------------------------
    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=10)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=(10, 15))

        self.tab_conn = self.tabview.add("🔐 GitHub Connection")
        self.tab_report = self.tabview.add("📊 Work Reporting")
        self.tab_update = self.tabview.add("🔄 Version & Updates")

        self._build_connection_tab()
        self._build_reporting_tab()
        self._build_updates_tab()

    # -----------------------------------------------------------------------
    # TAB 1: GitHub Connection
    # -----------------------------------------------------------------------
    def _build_connection_tab(self):
        parent = self.tab_conn

        # Info Box
        info_card = ctk.CTkFrame(parent, corner_radius=8, fg_color="#1e293b")
        info_card.pack(fill="x", padx=16, pady=(16, 12))

        ctk.CTkLabel(
            info_card,
            text="GitHub Authentication & Personal Access Token",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            info_card,
            text="Provide a Personal Access Token (Classic with 'repo' scope or Fine-Grained) to scan both Public & Private repositories without rate limits.",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8",
            wraplength=860,
            justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # Token Input Card
        input_card = ctk.CTkFrame(parent, corner_radius=8)
        input_card.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(input_card, text="Personal Access Token:", font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=16, pady=(14, 6))

        token_box = ctk.CTkFrame(input_card, fg_color="transparent")
        token_box.pack(fill="x", padx=16, pady=(0, 10))

        self.token_entry = ctk.CTkEntry(
            token_box,
            placeholder_text="Paste your GitHub token here (e.g. ghp_... or github_pat_...)",
            show="*",
            height=38,
            font=ctk.CTkFont(size=13)
        )
        self.token_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.show_token_btn = ctk.CTkButton(
            token_box,
            text="👁️ Show",
            width=80,
            height=38,
            fg_color="#334155",
            hover_color="#475569",
            command=self._toggle_token_visibility
        )
        self.show_token_btn.pack(side="left", padx=(0, 10))

        self.btn_connect = ctk.CTkButton(
            token_box,
            text="Connect & Test",
            width=140,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.test_connection
        )
        self.btn_connect.pack(side="left")

        # Remember token checkbox & Token Link
        opt_box = ctk.CTkFrame(input_card, fg_color="transparent")
        opt_box.pack(fill="x", padx=16, pady=(0, 14))

        self.remember_cb = ctk.CTkCheckBox(opt_box, text="Remember token on this device (%APPDATA%)", font=ctk.CTkFont(size=12))
        if self.config_mgr.get("remember_token", True):
            self.remember_cb.select()
        self.remember_cb.pack(side="left")

        btn_link = ctk.CTkButton(
            opt_box,
            text="🔗 Create Token on GitHub",
            font=ctk.CTkFont(size=12, underline=True),
            fg_color="transparent",
            text_color="#38bdf8",
            hover_color="#1e293b",
            width=180,
            command=lambda: webbrowser.open("https://github.com/settings/tokens")
        )
        btn_link.pack(side="right")

        # Connection Status Display Card
        self.profile_card = ctk.CTkFrame(parent, corner_radius=8, fg_color="#1e293b")
        self.profile_card.pack(fill="both", expand=True, padx=16, pady=12)

        self.lbl_profile_status = ctk.CTkLabel(
            self.profile_card,
            text="No active connection. Paste your token above and click 'Connect & Test'.",
            font=ctk.CTkFont(size=14),
            text_color="#94a3b8"
        )
        self.lbl_profile_status.pack(pady=40)

        # Clear Token button
        self.btn_clear_token = ctk.CTkButton(
            self.profile_card,
            text="Clear Saved Token",
            fg_color="#ef4444",
            hover_color="#dc2626",
            width=150,
            command=self._clear_token
        )

    def _toggle_token_visibility(self):
        if self.token_entry.cget("show") == "*":
            self.token_entry.configure(show="")
            self.show_token_btn.configure(text="🔒 Hide")
        else:
            self.token_entry.configure(show="*")
            self.show_token_btn.configure(text="👁️ Show")

    def _clear_token(self):
        self.config_mgr.clear_token()
        self.token_entry.delete(0, "end")
        self.status_pill.configure(text="⚪ Disconnected", fg_color="#1e293b", text_color="#94a3b8")
        self.lbl_profile_status.configure(text="Token cleared. Please enter a token above.", text_color="#94a3b8")
        self.btn_clear_token.pack_forget()
        self.cached_repos = []
        self._update_repo_dropdown()

    def test_connection(self):
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showwarning("Token Required", "Please enter a GitHub Personal Access Token.")
            return

        self.btn_connect.configure(state="disabled", text="Connecting...")
        self.status_pill.configure(text="🟡 Checking...", fg_color="#78350f", text_color="#fde68a")

        threading.Thread(target=self._run_connection_test, args=(token,), daemon=True).start()

    def _run_connection_test(self, token: str):
        try:
            client = GitHubClient(token=token)
            profile = client.get_authenticated_user()
            login = profile.get("login")

            if not login:
                raise RuntimeError("Could not retrieve user login. Token may be invalid or expired.")

            # Save token if checked
            if self.remember_cb.get():
                self.config_mgr.set("token", token)
                self.config_mgr.set("remember_token", True)

            # Fetch repositories list
            repos = client.get_repositories(visibility="all")
            self.cached_repos = repos
            self.client = client

            # Update UI on main thread
            self.after(0, self._on_connection_success, profile, len(repos))
        except Exception as err:
            self.after(0, self._on_connection_error, str(err))

    def _on_connection_success(self, profile: dict, repo_count: int):
        self.btn_connect.configure(state="normal", text="Connect & Test")
        login = profile.get("login", "Unknown")
        name = profile.get("name") or login
        email = profile.get("email") or "Private/None"

        self.status_pill.configure(text=f"🟢 {login}", fg_color="#064e3b", text_color="#a7f3d0")

        # Update Profile Card
        for widget in self.profile_card.winfo_children():
            widget.pack_forget()

        header = ctk.CTkLabel(
            self.profile_card,
            text=f"✔ Authenticated as {name} (@{login})",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#34d399"
        )
        header.pack(anchor="w", padx=20, pady=(16, 8))

        details_text = (
            f"• GitHub Login: {login}\n"
            f"• Verified Email: {email}\n"
            f"• Accessible Repositories: {repo_count} (Public & Private)\n"
            f"• Connection Status: Active with 5,000 API requests/hour"
        )
        ctk.CTkLabel(
            self.profile_card,
            text=details_text,
            font=ctk.CTkFont(size=13),
            text_color="#e2e8f0",
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 16))

        self.btn_clear_token.pack(anchor="w", padx=20, pady=(0, 16))

        # Update Repositories dropdown in Reporting tab
        self._update_repo_dropdown()

    def _on_connection_error(self, error_msg: str):
        self.btn_connect.configure(state="normal", text="Connect & Test")
        self.status_pill.configure(text="🔴 Connection Failed", fg_color="#7f1d1d", text_color="#fecaca")
        self.lbl_profile_status.configure(
            text=f"Authentication Failed:\n{error_msg}\n\nPlease check that your token is valid and has 'repo' scope.",
            text_color="#f87171"
        )

    # -----------------------------------------------------------------------
    # TAB 2: Work & Change Reporting
    # -----------------------------------------------------------------------
    def _build_reporting_tab(self):
        parent = self.tab_report

        # Date Selection Box
        date_card = ctk.CTkFrame(parent, corner_radius=8)
        date_card.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(date_card, text="📅 Date Range:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 6))

        date_row = ctk.CTkFrame(date_card, fg_color="transparent")
        date_row.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(date_row, text="From:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(0, 6))
        self.start_date_entry = ctk.CTkEntry(date_row, width=120, height=32, font=ctk.CTkFont(size=13))
        self.start_date_entry.insert(0, (date.today() - timedelta(days=7)).strftime("%Y-%m-%d"))
        self.start_date_entry.pack(side="left", padx=(0, 4))
        self.btn_cal_start = ctk.CTkButton(
            date_row,
            text="📅",
            width=36,
            height=32,
            font=ctk.CTkFont(size=14),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._open_date_picker(self.start_date_entry, "Select Start Date")
        )
        self.btn_cal_start.pack(side="left", padx=(0, 20))
        self.start_date_entry.bind("<Double-Button-1>", lambda e: self._open_date_picker(self.start_date_entry, "Select Start Date"))

        ctk.CTkLabel(date_row, text="To:", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=(0, 6))
        self.end_date_entry = ctk.CTkEntry(date_row, width=120, height=32, font=ctk.CTkFont(size=13))
        self.end_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))
        self.end_date_entry.pack(side="left", padx=(0, 4))
        self.btn_cal_end = ctk.CTkButton(
            date_row,
            text="📅",
            width=36,
            height=32,
            font=ctk.CTkFont(size=14),
            fg_color="#334155",
            hover_color="#475569",
            command=lambda: self._open_date_picker(self.end_date_entry, "Select End Date")
        )
        self.btn_cal_end.pack(side="left", padx=(0, 20))
        self.end_date_entry.bind("<Double-Button-1>", lambda e: self._open_date_picker(self.end_date_entry, "Select End Date"))

        # Quick Preset Buttons
        presets_frame = ctk.CTkFrame(date_card, fg_color="transparent")
        presets_frame.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(presets_frame, text="Quick Presets:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#94a3b8").pack(side="left", padx=(0, 10))

        presets = [
            ("Today", self._set_preset_today),
            ("Yesterday", self._set_preset_yesterday),
            ("Last 7 Days", self._set_preset_7d),
            ("This Week", self._set_preset_this_week),
            ("Last 14 Days", self._set_preset_14d),
            ("Last 30 Days", self._set_preset_30d),
            ("This Month", self._set_preset_this_month),
        ]
        for title, cmd in presets:
            ctk.CTkButton(
                presets_frame,
                text=title,
                width=80,
                height=26,
                font=ctk.CTkFont(size=11),
                fg_color="#334155",
                hover_color="#475569",
                command=cmd
            ).pack(side="left", padx=3)

        # Filters Card
        filter_card = ctk.CTkFrame(parent, corner_radius=8)
        filter_card.pack(fill="x", padx=16, pady=6)

        ctk.CTkLabel(filter_card, text="⚙️ Scope & Filter Options:", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=16, pady=(12, 6))

        filter_row = ctk.CTkFrame(filter_card, fg_color="transparent")
        filter_row.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkLabel(filter_row, text="Repository:", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.repo_option_menu = ctk.CTkOptionMenu(
            filter_row,
            values=["All Accessible Repositories"],
            width=240,
            height=32,
            font=ctk.CTkFont(size=12)
        )
        self.repo_option_menu.pack(side="left", padx=(0, 24))

        self.cb_skip_merges = ctk.CTkCheckBox(filter_row, text="Skip Merge Commits (Focus on real work)", font=ctk.CTkFont(size=12))
        self.cb_skip_merges.select()
        self.cb_skip_merges.pack(side="left", padx=(0, 16))

        self.cb_stats = ctk.CTkCheckBox(filter_row, text="Include Detailed Diff Stats (+ / - lines)", font=ctk.CTkFont(size=12))
        self.cb_stats.pack(side="left")

        # Action & Progress
        action_card = ctk.CTkFrame(parent, corner_radius=8, fg_color="#1e293b")
        action_card.pack(fill="x", padx=16, pady=8)

        btn_box = ctk.CTkFrame(action_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=16, pady=12)

        self.btn_generate = ctk.CTkButton(
            btn_box,
            text="🚀 Generate Work & QA Reports (PDF, HTML, Text, MD)",
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.start_generate_reports
        )
        self.btn_generate.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self.progress_bar = ctk.CTkProgressBar(action_card, mode="indeterminate", height=6)
        self.lbl_status = ctk.CTkLabel(action_card, text="Ready to generate reports.", font=ctk.CTkFont(size=12), text_color="#94a3b8")
        self.lbl_status.pack(anchor="w", padx=18, pady=(0, 8))

        # Results & Export Hub
        self.results_frame = ctk.CTkFrame(parent, corner_radius=8)
        self.results_frame.pack(fill="both", expand=True, padx=16, pady=(8, 12))

        self.lbl_results_placeholder = ctk.CTkLabel(
            self.results_frame,
            text="Generated reports and download actions will appear here after running.",
            font=ctk.CTkFont(size=13),
            text_color="#64748b"
        )
        self.lbl_results_placeholder.pack(pady=30)

    # Date Picker & Presets
    def _open_date_picker(self, target_entry: ctk.CTkEntry, title: str = "Select Date"):
        try:
            CTkDatePicker(self, target_entry=target_entry, title=title)
        except Exception as e:
            messagebox.showerror("Date Picker", str(e))

    def _set_preset_today(self):
        t = date.today().strftime("%Y-%m-%d")
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, t)
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, t)

    def _set_preset_yesterday(self):
        y = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, y)
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, y)

    def _set_preset_7d(self):
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, (date.today() - timedelta(days=7)).strftime("%Y-%m-%d"))
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

    def _set_preset_this_week(self):
        today = date.today()
        start = today - timedelta(days=today.weekday())
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, start.strftime("%Y-%m-%d"))
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, today.strftime("%Y-%m-%d"))

    def _set_preset_14d(self):
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, (date.today() - timedelta(days=14)).strftime("%Y-%m-%d"))
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

    def _set_preset_30d(self):
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, (date.today() - timedelta(days=30)).strftime("%Y-%m-%d"))
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, date.today().strftime("%Y-%m-%d"))

    def _set_preset_this_month(self):
        today = date.today()
        start = today.replace(day=1)
        self.start_date_entry.delete(0, "end"); self.start_date_entry.insert(0, start.strftime("%Y-%m-%d"))
        self.end_date_entry.delete(0, "end"); self.end_date_entry.insert(0, today.strftime("%Y-%m-%d"))

    def _update_repo_dropdown(self):
        if self.cached_repos:
            names = ["All Accessible Repositories"] + [r.get("name", "") for r in self.cached_repos if r.get("name")]
            self.repo_option_menu.configure(values=names)
            self.repo_option_menu.set(f"All Repositories ({len(self.cached_repos)})")
        else:
            self.repo_option_menu.configure(values=["All Accessible Repositories"])
            self.repo_option_menu.set("All Accessible Repositories")

    def start_generate_reports(self):
        if self.is_generating:
            return

        token = self.token_entry.get().strip() or self.config_mgr.get("token")
        if not self.client:
            self.client = GitHubClient(token=token if token else None)

        start_val = self.start_date_entry.get().strip()
        end_val = self.end_date_entry.get().strip()

        try:
            start_dt, end_dt = resolve_date_range(start_val, end_val)
        except ValueError as e:
            messagebox.showerror("Invalid Date Range", str(e))
            return

        selected_repo = self.repo_option_menu.get()
        repos_filter = None
        if not selected_repo.startswith("All"):
            repos_filter = [selected_repo]

        skip_merges = bool(self.cb_skip_merges.get())
        include_stats = bool(self.cb_stats.get())

        self.is_generating = True
        self.btn_generate.configure(state="disabled", text="Scanning & Generating Reports...")
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 6))
        self.progress_bar.start()
        self.lbl_status.configure(text="Scanning GitHub repositories...", text_color="#38bdf8")

        threading.Thread(
            target=self._run_report_generation,
            args=(start_dt, end_dt, repos_filter, skip_merges, include_stats),
            daemon=True
        ).start()

    def _run_report_generation(self, start_dt, end_dt, repos_filter, skip_merges, include_stats):
        try:
            collector = WorkCollector(
                client=self.client,
                start_dt=start_dt,
                end_dt=end_dt,
                specific_repos=repos_filter,
                skip_merges=skip_merges,
                include_stats=include_stats
            )
            commits = collector.collect()

            self.after(0, self.lbl_status.configure, {"text": f"Found {len(commits)} commits. Compiling reports..."})

            reporter = ReportGenerator(commits, start_dt, end_dt, user_identity=collector.primary_identity)

            # File export
            start_str = start_dt.strftime("%Y-%m-%d")
            end_str = end_dt.strftime("%Y-%m-%d")
            reports_dir = get_default_reports_dir()
            base_name = f"github_work_report_{start_str}_to_{end_str}"
            base_target = os.path.join(reports_dir, base_name)

            saved_files = {}
            saved_files["md"] = reporter.save_markdown(base_target + ".md")
            saved_files["html"] = reporter.save_html(base_target + ".html")
            saved_files["txt"] = reporter.save_text_doc(base_target + ".txt")

            pdf_path = reporter.save_pdf(base_target + ".pdf")
            if pdf_path:
                saved_files["pdf"] = pdf_path

            self.last_generated_files = saved_files
            self.after(0, self._on_generation_success, commits, reporter, saved_files)
        except Exception as err:
            self.after(0, self._on_generation_error, str(err))

    def _on_generation_success(self, commits: list, reporter: ReportGenerator, saved_files: dict):
        self.is_generating = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.btn_generate.configure(state="normal", text="🚀 Generate Work & QA Reports (PDF, HTML, Text, MD)")
        self.lbl_status.configure(text=f"✔ Successfully generated reports! ({len(commits)} commits processed)", text_color="#34d399")

        # Clear placeholder
        for w in self.results_frame.winfo_children():
            w.pack_forget()

        # Stats Row
        active_repos = sorted(list({c.repo_name for c in commits}))
        categorized = reporter.analyzer.get_categorized_changes()
        sec_count = len(categorized.get("security", {}).get("items", []))
        feat_count = len(categorized.get("features", {}).get("items", [])) + len(categorized.get("ui", {}).get("items", []))

        stats_box = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        stats_box.pack(fill="x", padx=16, pady=(12, 12))

        kpis = [
            ("Total Deliverables", len(commits), "#f8fafc"),
            ("Active Repos", len(active_repos), "#38bdf8"),
            ("Security & Access", sec_count, "#818cf8"),
            ("Features & UI", feat_count, "#34d399"),
        ]
        for label, val, color in kpis:
            card = ctk.CTkFrame(stats_box, corner_radius=6, fg_color="#1e293b")
            card.pack(side="left", fill="both", expand=True, padx=4)
            ctk.CTkLabel(card, text=str(val), font=ctk.CTkFont(size=20, weight="bold"), text_color=color).pack(pady=(8, 2))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=11), text_color="#94a3b8").pack(pady=(0, 8))

        # Action Buttons Grid
        actions_card = ctk.CTkFrame(self.results_frame, corner_radius=8, fg_color="#1e293b")
        actions_card.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(actions_card, text="Export & View Generated Documents:", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(anchor="w", padx=16, pady=(10, 8))

        btns_row = ctk.CTkFrame(actions_card, fg_color="transparent")
        btns_row.pack(fill="x", padx=16, pady=(0, 12))

        if "pdf" in saved_files:
            ctk.CTkButton(
                btns_row,
                text="📄 Open PDF Report",
                fg_color="#059669",
                hover_color="#047857",
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: os.startfile(saved_files["pdf"])
            ).pack(side="left", padx=4)

        if "html" in saved_files:
            ctk.CTkButton(
                btns_row,
                text="🌐 Open HTML Dashboard",
                fg_color="#0284c7",
                hover_color="#0369a1",
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: webbrowser.open(f"file://{saved_files['html']}")
            ).pack(side="left", padx=4)

        if "txt" in saved_files:
            ctk.CTkButton(
                btns_row,
                text="📋 Open Plain-Text Doc",
                fg_color="#475569",
                hover_color="#334155",
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: os.startfile(saved_files["txt"])
            ).pack(side="left", padx=4)

        if "md" in saved_files:
            ctk.CTkButton(
                btns_row,
                text="📝 Open Markdown",
                fg_color="#334155",
                hover_color="#1e293b",
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: os.startfile(saved_files["md"])
            ).pack(side="left", padx=4)

        reports_folder = os.path.dirname(saved_files.get("html", ""))
        if reports_folder and os.path.isdir(reports_folder):
            ctk.CTkButton(
                btns_row,
                text="📂 Open Folder",
                fg_color="#6366f1",
                hover_color="#4f46e5",
                height=34,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda: os.startfile(reports_folder)
            ).pack(side="right", padx=4)

    def _on_generation_error(self, err_msg: str):
        self.is_generating = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.btn_generate.configure(state="normal", text="🚀 Generate Work & QA Reports (PDF, HTML, Text, MD)")
        self.lbl_status.configure(text=f"Error generating reports: {err_msg}", text_color="#ef4444")
        messagebox.showerror("Report Generation Error", err_msg)

    # -----------------------------------------------------------------------
    # TAB 3: Version & Updates
    # -----------------------------------------------------------------------
    def _build_updates_tab(self):
        parent = self.tab_update

        card = ctk.CTkFrame(parent, corner_radius=8, fg_color="#1e293b")
        card.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(
            card,
            text="Application Version & Auto-Update",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#f8fafc"
        ).pack(anchor="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(
            card,
            text=f"Currently running version: v{APP_VERSION}",
            font=ctk.CTkFont(size=13),
            text_color="#94a3b8"
        ).pack(anchor="w", padx=20, pady=(0, 14))

        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.pack(fill="x", padx=20, pady=(0, 16))

        self.btn_check_update = ctk.CTkButton(
            action_row,
            text="🔍 Check for Updates",
            height=36,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self.check_for_updates
        )
        self.btn_check_update.pack(side="left", padx=(0, 10))

        self.btn_shortcut = ctk.CTkButton(
            action_row,
            text="📌 Create Desktop Shortcut",
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color="#334155",
            hover_color="#475569",
            command=self.create_desktop_shortcut
        )
        self.btn_shortcut.pack(side="left", padx=(0, 14))

        self.lbl_update_spinner = ctk.CTkLabel(
            action_row,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="#38bdf8"
        )
        self.lbl_update_spinner.pack(side="left")

        # Update Display Box
        self.update_display_card = ctk.CTkFrame(parent, corner_radius=8)
        self.update_display_card.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.lbl_update_status = ctk.CTkLabel(
            self.update_display_card,
            text="Click 'Check for Updates' to verify if a new release is available.",
            font=ctk.CTkFont(size=13),
            text_color="#64748b"
        )
        self.lbl_update_status.pack(pady=40)

    def create_desktop_shortcut(self):
        try:
            import app_installer
            is_frozen = getattr(sys, "frozen", False)
            target = sys.executable if is_frozen else app_installer.get_installed_exe_path()
            res = app_installer.setup_desktop_and_start_menu_shortcuts(target)
            if res.get("desktop") or res.get("start_menu"):
                messagebox.showinfo("Desktop Shortcut", "✔ Desktop & Start Menu shortcuts created successfully!\nYou can now open the app directly from your Desktop or Windows Start Menu.")
            else:
                messagebox.showwarning("Desktop Shortcut", "Could not create Desktop shortcut automatically.")
        except Exception as e:
            messagebox.showerror("Shortcut Error", str(e))

    def check_for_updates(self):
        self.btn_check_update.configure(state="disabled", text="Checking for updates...")
        self.lbl_update_spinner.configure(text="Checking GitHub...")

        token = self.token_entry.get().strip() or self.config_mgr.get("token")
        threading.Thread(target=self._run_check_updates, args=(token,), daemon=True).start()

    def _run_check_updates(self, token: str):
        updater = UpdateManager(repo_full_name=DEFAULT_GITHUB_REPO, current_version=APP_VERSION, token=token)
        res = updater.check_for_updates()
        self.after(0, self._on_update_result, res, updater)

    def _on_update_result(self, res: dict, updater: UpdateManager):
        self.btn_check_update.configure(state="normal", text="🔍 Check for Updates")
        self.lbl_update_spinner.configure(text="")

        for w in self.update_display_card.winfo_children():
            w.pack_forget()

        if res.get("error"):
            box = ctk.CTkFrame(self.update_display_card, fg_color="transparent")
            box.pack(pady=40)
            ctk.CTkLabel(box, text="⚠️", font=ctk.CTkFont(size=32)).pack(pady=(0, 8))
            ctk.CTkLabel(
                box,
                text=f"Unable to check for updates:\n{res['error']}\n\nPlease check your internet connection.",
                font=ctk.CTkFont(size=13),
                text_color="#f87171",
                justify="center"
            ).pack()
            return

        if not res.get("has_update"):
            box = ctk.CTkFrame(self.update_display_card, fg_color="transparent")
            box.pack(pady=40)
            ctk.CTkLabel(box, text="✔", font=ctk.CTkFont(size=36), text_color="#34d399").pack(pady=(0, 8))
            ctk.CTkLabel(
                box,
                text=f"You are running the latest version! (v{APP_VERSION})",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="#34d399"
            ).pack(pady=(0, 6))
            ctk.CTkLabel(
                box,
                text="No new updates are currently available. Your application is up to date.",
                font=ctk.CTkFont(size=12),
                text_color="#94a3b8"
            ).pack()
            return

        # An update is available!
        header = ctk.CTkLabel(
            self.update_display_card,
            text=f"🎉 Update Available: {res.get('latest_version')} (Released {res.get('published_at')})",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#38bdf8"
        )
        header.pack(anchor="w", padx=20, pady=(16, 8))

        # Changelog / Release Notes
        notes_title = ctk.CTkLabel(self.update_display_card, text="Release Notes:", font=ctk.CTkFont(size=12, weight="bold"))
        notes_title.pack(anchor="w", padx=20, pady=(0, 4))

        notes_box = ctk.CTkTextbox(self.update_display_card, height=140, font=ctk.CTkFont(size=12))
        notes_box.pack(fill="x", padx=20, pady=(0, 12))
        notes_box.insert("1.0", res.get("release_notes", ""))
        notes_box.configure(state="disabled")

        # Download & Install Button
        asset_url = res.get("asset_url")
        if asset_url:
            size_mb = res.get("asset_size", 0) / (1024 * 1024)
            size_str = f" ({size_mb:.1f} MB)" if size_mb > 0 else ""

            btn_update = ctk.CTkButton(
                self.update_display_card,
                text=f"⬇️ Download & Install Update{size_str}",
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color="#059669",
                hover_color="#047857",
                height=38,
                command=lambda: self.start_download_update(updater, asset_url)
            )
            btn_update.pack(anchor="w", padx=20, pady=(0, 16))
        else:
            warn_card = ctk.CTkFrame(self.update_display_card, fg_color="#334155", corner_radius=6)
            warn_card.pack(fill="x", padx=20, pady=(0, 14))
            ctk.CTkLabel(
                warn_card,
                text=f"⚠️ Release {res.get('latest_version')} is published on GitHub, but no executable (.exe) file was uploaded to the release yet.\n\n"
                     "When the .exe is attached to the GitHub release, 1-click update will automatically download and install it here.",
                font=ctk.CTkFont(size=12),
                text_color="#fbbf24",
                justify="left"
            ).pack(anchor="w", padx=16, pady=12)

            btn_web = ctk.CTkButton(
                self.update_display_card,
                text="🌐 Open Release Page on GitHub",
                command=lambda: webbrowser.open(res.get("html_url", ""))
            )
            btn_web.pack(anchor="w", padx=20, pady=(0, 16))

    def start_download_update(self, updater: UpdateManager, asset_url: str):
        progress_popup = ctk.CTkToplevel(self)
        progress_popup.title("Downloading Update")
        progress_popup.geometry("420x180")
        progress_popup.resizable(False, False)
        progress_popup.grab_set()

        ctk.CTkLabel(progress_popup, text="Downloading new version from GitHub...", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 10))
        p_bar = ctk.CTkProgressBar(progress_popup, width=340)
        p_bar.pack(pady=10)
        p_bar.set(0)

        p_lbl = ctk.CTkLabel(progress_popup, text="Connecting to GitHub...", font=ctk.CTkFont(size=12), text_color="#94a3b8")
        p_lbl.pack(pady=(0, 15))

        def progress_cb(read_bytes: int, total_bytes: int):
            if total_bytes > 0:
                fraction = min(1.0, read_bytes / total_bytes)
                p_bar.set(fraction)
                read_mb = read_bytes / (1024 * 1024)
                total_mb = total_bytes / (1024 * 1024)
                p_lbl.configure(text=f"{read_mb:.1f} MB / {total_mb:.1f} MB ({int(fraction * 100)}%)")

        def download_thread():
            try:
                temp_exe = updater.download_update(asset_url, progress_callback=progress_cb)
                self.after(0, self._on_download_complete, progress_popup, temp_exe)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Download Failed", f"Could not download update: {e}"))
                self.after(0, progress_popup.destroy)

        threading.Thread(target=download_thread, daemon=True).start()

    def _on_download_complete(self, popup, temp_exe: str):
        popup.destroy()
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen:
            messagebox.showinfo(
                "Update Downloaded",
                f"Running from Python source code.\nDownloaded new version executable to:\n{temp_exe}\n\nWhen bundled as an .exe, the app will auto-replace itself!"
            )
            return

        confirm = messagebox.askyesno(
            "Install Update Now",
            "Update downloaded successfully!\n\nWould you like to restart the application now to apply the update?"
        )
        if confirm:
            UpdateManager.apply_update_and_restart(temp_exe)


def main():
    app = WorkReporterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
