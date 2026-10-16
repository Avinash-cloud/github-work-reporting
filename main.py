"""
GitHub Work Reporter - Application Entry Point
==============================================
Launches the CustomTkinter GUI by default when double-clicked,
or routes to the CLI reporter if command-line arguments are provided.
"""

import sys
import os
import io

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


def run():
    # If explicit CLI flags are provided (other than just script name), route to CLI
    cli_flags = {"--start", "-s", "--end", "-e", "--author", "-a", "--token", "-t", "--cli", "--help", "-h", "--stats", "--json", "--all-formats"}
    has_cli_args = any(arg in cli_flags for arg in sys.argv[1:])

    if has_cli_args and "--gui" not in sys.argv:
        import reportingscript
        reportingscript.main()
    else:
        import app_gui
        app_gui.main()

if __name__ == "__main__":
    run()
