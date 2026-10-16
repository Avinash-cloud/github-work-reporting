"""
GitHub Work Reporter - Application Entry Point
==============================================
Launches the CustomTkinter GUI by default when double-clicked,
or routes to the CLI reporter if command-line arguments are provided.
"""

import sys
import os

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
