"""
GitHub Commit & Work Reporting Script
======================================
Fetches commit changes made across public and private GitHub repositories
for a given date range and generates a comprehensive, day-wise work report.

Features:
- Accesses both Public and Private repositories (with GitHub Personal Access Token).
- Gracefully falls back to public repositories if no token is provided.
- Intelligently detects user identities (GitHub login, git config name/email, variations).
- Groups work day-by-day and repository-by-repository in local timezone.
- Highlights merge commits vs direct work commits (with optional --no-merges flag).
- Generates beautiful Terminal output and saves a GitHub Flavored Markdown report.
- Optional detailed diff statistics (lines added, deleted, files changed via --stats).
- Supports interactive prompts or command-line arguments.
- Zero mandatory external dependencies (uses standard library; loads python-dotenv if present).
"""

import os
import sys
import json
import re
import argparse
import subprocess
import shutil
import html
from datetime import datetime, date, time, timedelta, timezone
import urllib.request
import urllib.error
import urllib.parse


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

# Ensure UTF-8 output encoding for Windows command line / PowerShell
try:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Attempt to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------------------
# ANSI Terminal Styling
# ---------------------------------------------------------------------------
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"

    # Colors
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"


# Enable ANSI escape sequences on Windows if possible
if sys.platform == "win32":
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass


def colorize(text: str, color_code: str) -> str:
    try:
        if sys.stdout and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
            return f"{color_code}{text}{Style.RESET}"
    except Exception:
        pass
    return text



# ---------------------------------------------------------------------------
# Helper: Local Git Configuration
# ---------------------------------------------------------------------------
def get_local_git_config() -> tuple[str | None, str | None]:
    """Retrieves git user.name and user.email from local git config if available."""
    name, email = None, None
    try:
        res_name = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, check=False
        )
        if res_name.returncode == 0:
            name = res_name.stdout.strip() or None
    except Exception:
        pass

    try:
        res_email = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, check=False
        )
        if res_email.returncode == 0:
            email = res_email.stdout.strip() or None
    except Exception:
        pass

    return name, email


# ---------------------------------------------------------------------------
# GitHub API Client
# ---------------------------------------------------------------------------
class GitHubClient:
    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self.token = token.strip() if token else None

    def _make_request(self, endpoint: str, params: dict | None = None) -> tuple[any, dict]:
        """Performs an HTTP GET request to GitHub API and returns (json_data, headers)."""
        url = endpoint if endpoint.startswith("http") else f"{self.BASE_URL}{endpoint}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}" if "?" not in url else f"{url}&{query}"

        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        req.add_header("User-Agent", "GitHub-Daywise-Work-Reporter")

        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                headers = dict(resp.headers)
                body = resp.read().decode("utf-8")
                return json.loads(body), headers
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message", err_body)
            except Exception:
                msg = err_body

            if err.code == 401:
                raise RuntimeError(
                    "GitHub Authentication Failed (401 Unauthorized).\n"
                    "Please verify that your GitHub Personal Access Token is valid and has not expired."
                ) from err
            elif err.code == 403:
                rate_limit_remaining = err.headers.get("x-ratelimit-remaining", "unknown")
                if rate_limit_remaining == "0":
                    reset_time = err.headers.get("x-ratelimit-reset", "")
                    reset_str = ""
                    if reset_time.isdigit():
                        reset_dt = datetime.fromtimestamp(int(reset_time))
                        reset_str = f" Rate limit resets at: {reset_dt.strftime('%Y-%m-%d %H:%M:%S')}"
                    raise RuntimeError(
                        f"GitHub API Rate Limit Exceeded.{reset_str}\n"
                        "Provide a Personal Access Token with --token or in .env to get 5,000 requests/hour."
                    ) from err
                raise RuntimeError(f"GitHub API Forbidden (403): {msg}") from err
            elif err.code == 404:
                return None, {}
            else:
                raise RuntimeError(f"GitHub API Error ({err.code}): {msg}") from err
        except urllib.error.URLError as err:
            raise RuntimeError(f"Network connection error while contacting GitHub: {err.reason}") from err

    def paginate(self, endpoint: str, params: dict | None = None, max_pages: int = 50) -> list:
        """Fetches all pages for a paginated GitHub endpoint."""
        items = []
        p = dict(params or {})
        p["per_page"] = p.get("per_page", 100)
        p["page"] = 1

        while p["page"] <= max_pages:
            data, headers = self._make_request(endpoint, p)
            if not data or not isinstance(data, list):
                break
            items.extend(data)
            if len(data) < p["per_page"]:
                break
            p["page"] += 1

        return items

    def get_authenticated_user(self) -> dict:
        """Fetches authenticated user profile."""
        if not self.token:
            return {}
        data, _ = self._make_request("/user")
        return data or {}

    def get_user_emails(self) -> list[str]:
        """Fetches all verified emails associated with the authenticated token."""
        if not self.token:
            return []
        try:
            data, _ = self._make_request("/user/emails")
            if isinstance(data, list):
                return [item["email"].lower() for item in data if "email" in item]
        except Exception:
            pass
        return []

    def get_repositories(
        self,
        fallback_username: str | None = None,
        visibility: str = "all",
        affiliation: str = "owner,collaborator,organization_member"
    ) -> list[dict]:
        """
        Fetches repositories for the user.
        - If token is present: calls /user/repos (includes private repos & collaborator repos).
        - If token is missing: calls /users/{username}/repos (public repos only).
        """
        if self.token:
            params = {
                "visibility": visibility,
                "affiliation": affiliation,
                "sort": "pushed",
                "direction": "desc",
                "per_page": 100
            }
            return self.paginate("/user/repos", params)
        elif fallback_username:
            params = {
                "sort": "pushed",
                "direction": "desc",
                "per_page": 100
            }
            return self.paginate(f"/users/{fallback_username}/repos", params)
        else:
            raise RuntimeError(
                "No GitHub token or username provided. "
                "Provide a token via --token / .env or specify --author <username>."
            )

    def get_commits(
        self,
        owner: str,
        repo: str,
        since_iso: str,
        until_iso: str,
        author: str | None = None
    ) -> list[dict]:
        """Fetches commits for a specific repository within the given ISO timestamps."""
        params = {
            "since": since_iso,
            "until": until_iso,
            "per_page": 100
        }
        if author:
            params["author"] = author

        return self.paginate(f"/repos/{owner}/{repo}/commits", params)

    def get_commit_detail(self, owner: str, repo: str, sha: str) -> dict | None:
        """Fetches detailed commit stats (additions, deletions, files)."""
        try:
            data, _ = self._make_request(f"/repos/{owner}/{repo}/commits/{sha}")
            return data
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Date Parsing & Range Resolution
# ---------------------------------------------------------------------------
def parse_date_str(date_str: str) -> date:
    """Parses standard YYYY-MM-DD or relative shortcut string into a date object."""
    date_str = date_str.strip().lower()
    today = date.today()

    if date_str in ("today", "now"):
        return today
    elif date_str == "yesterday":
        return today - timedelta(days=1)
    elif date_str in ("7d", "7days", "week", "last-week", "past-7-days"):
        return today - timedelta(days=7)
    elif date_str in ("14d", "14days", "2weeks"):
        return today - timedelta(days=14)
    elif date_str in ("30d", "30days", "month", "last-30-days"):
        return today - timedelta(days=30)
    elif date_str == "this-week":
        return today - timedelta(days=today.weekday())
    elif date_str == "this-month":
        return today.replace(day=1)

    # Standard YYYY-MM-DD
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(
            f"Invalid date format '{date_str}'. Expected 'YYYY-MM-DD' (e.g. 2026-10-01) "
            f"or relative keyword (today, yesterday, 7d, 14d, 30d, this-week, this-month)."
        )


def resolve_date_range(start_input: str | None, end_input: str | None) -> tuple[datetime, datetime]:
    """
    Resolves start and end datetimes in local timezone with full day boundaries:
    start: 00:00:00 local time
    end:   23:59:59.999999 local time
    """
    local_tz = datetime.now().astimezone().tzinfo

    today = date.today()
    start_date = parse_date_str(start_input) if start_input else (today - timedelta(days=7))
    end_date = parse_date_str(end_input) if end_input else today

    if start_date > end_date:
        raise ValueError(f"Start date ({start_date}) cannot be after end date ({end_date}).")

    start_dt = datetime.combine(start_date, time.min, tzinfo=local_tz)
    end_dt = datetime.combine(end_date, time.max, tzinfo=local_tz)

    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Commit Data Representation
# ---------------------------------------------------------------------------
class CommitInfo:
    def __init__(
        self,
        sha: str,
        repo_name: str,
        repo_full_name: str,
        repo_url: str,
        message: str,
        author_name: str,
        author_email: str,
        author_login: str | None,
        commit_dt_local: datetime,
        commit_url: str,
        stats: dict | None = None
    ):
        self.sha = sha
        self.short_sha = sha[:7]
        self.repo_name = repo_name
        self.repo_full_name = repo_full_name
        self.repo_url = repo_url
        self.message = message
        self.summary = message.strip().split("\n")[0]
        self.body = "\n".join(message.strip().split("\n")[1:]).strip()
        self.is_merge = self.summary.lower().startswith("merge branch") or self.summary.lower().startswith("merge pull request")
        self.author_name = author_name
        self.author_email = author_email
        self.author_login = author_login
        self.commit_dt_local = commit_dt_local
        self.day_str = commit_dt_local.strftime("%Y-%m-%d")
        self.weekday = commit_dt_local.strftime("%A")
        self.time_str = commit_dt_local.strftime("%I:%M %p")
        self.commit_url = commit_url
        self.stats = stats or {}


# ---------------------------------------------------------------------------
# Work Collector Engine
# ---------------------------------------------------------------------------
class WorkCollector:
    def __init__(
        self,
        client: GitHubClient,
        start_dt: datetime,
        end_dt: datetime,
        fallback_username: str | None = None,
        specific_repos: list[str] | None = None,
        exclude_repos: list[str] | None = None,
        include_stats: bool = False,
        all_authors: bool = False,
        skip_merges: bool = False,
        target_author: str | None = None,
        visibility: str = "all",
        affiliation: str = "owner,collaborator,organization_member"
    ):
        self.client = client
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.fallback_username = fallback_username
        self.specific_repos = [r.lower() for r in (specific_repos or [])]
        self.exclude_repos = [r.lower() for r in (exclude_repos or [])]
        self.include_stats = include_stats
        self.all_authors = all_authors
        self.skip_merges = skip_merges
        self.target_author = target_author
        self.visibility = visibility
        self.affiliation = affiliation

        # Author matching sets
        self.user_logins = set()
        self.user_emails = set()
        self.user_names = set()
        self.primary_identity = fallback_username or "Developer"

    def identify_user(self):
        """Discovers the user's logins, emails, and names for author matching."""
        if self.target_author:
            self.user_logins.add(self.target_author.lower())
            self.user_names.add(self.target_author.lower())
            self.primary_identity = self.target_author
            print(colorize(f"-> Filtering commits specifically for author: {self.target_author}", Style.CYAN))
            return

        # Local git config
        git_name, git_email = get_local_git_config()
        if git_name:
            self.user_names.add(git_name.lower())
            self.primary_identity = git_name
        if git_email:
            self.user_emails.add(git_email.lower())

        if self.fallback_username:
            self.user_logins.add(self.fallback_username.lower())
            self.user_names.add(self.fallback_username.lower())
            self.primary_identity = self.fallback_username

        # GitHub user profile if authenticated
        if self.client.token:
            try:
                user_info = self.client.get_authenticated_user()
                if user_info:
                    login = user_info.get("login")
                    name = user_info.get("name")
                    email = user_info.get("email")
                    if login:
                        self.user_logins.add(login.lower())
                        self.primary_identity = login
                    if name:
                        self.user_names.add(name.lower())
                    if email:
                        self.user_emails.add(email.lower())
            except Exception as e:
                print(colorize(f"Warning: Could not fetch user profile: {e}", Style.YELLOW))

            try:
                emails = self.client.get_user_emails()
                for em in emails:
                    self.user_emails.add(em.lower())
            except Exception:
                pass

    def is_commit_by_user(self, commit_data: dict, repo_owner: str) -> bool:
        """Determines if a commit belongs to the target user."""
        if self.all_authors:
            return True

        # Check GitHub author login
        gh_author = commit_data.get("author")
        if gh_author and isinstance(gh_author, dict):
            login = (gh_author.get("login") or "").lower()
            if login and login in self.user_logins:
                return True

        # Check Git commit author metadata
        commit_obj = commit_data.get("commit", {})
        git_author = commit_obj.get("author", {})
        author_email = (git_author.get("email") or "").lower()
        author_name = (git_author.get("name") or "").lower()

        if author_email and author_email in self.user_emails:
            return True
        if author_name and author_name in self.user_names:
            return True

        # Check committer metadata
        git_committer = commit_obj.get("committer", {})
        committer_email = (git_committer.get("email") or "").lower()
        if committer_email and committer_email in self.user_emails:
            return True

        # Loose match for variations (e.g. "Avinash-cloud" vs "Avinash-cloude")
        for u in self.user_names | self.user_logins:
            clean_u = re.sub(r"[^a-zA-Z0-9]", "", u)
            clean_author = re.sub(r"[^a-zA-Z0-9]", "", author_name)
            if len(clean_u) >= 5 and (clean_u in clean_author or clean_author in clean_u):
                return True

        # If repo is owned by user and author name matches repo owner
        if repo_owner and repo_owner.lower() in self.user_logins and author_name:
            if repo_owner.lower() in author_name.lower():
                return True

        return False

    def collect(self) -> list[CommitInfo]:
        """Main collection routine. Queries repos, fetches commits, parses details."""
        self.identify_user()

        print(colorize("\n🔍 Scanning repositories on GitHub...", Style.CYAN + Style.BOLD))
        repos = self.client.get_repositories(
            fallback_username=self.fallback_username,
            visibility=self.visibility,
            affiliation=self.affiliation
        )

        private_count = sum(1 for r in repos if r.get("private"))
        public_count = len(repos) - private_count
        print(f"   Found {colorize(str(len(repos)), Style.BOLD)} repositories "
              f"({colorize(str(public_count) + ' public', Style.GREEN)}, "
              f"{colorize(str(private_count) + ' private', Style.YELLOW)}).")

        # Detect if a Fine-Grained token is restricted to public repos only
        if self.client.token and self.client.token.startswith("github_pat_") and private_count == 0:
            print(colorize("\n⚠️  NOTICE: Your Fine-Grained Token is restricted to PUBLIC repos only!", Style.YELLOW + Style.BOLD))
            print(colorize("   GitHub is hiding your private repositories because 'Repository access' was set to 'Public Repositories (read-only)'.", Style.YELLOW))
            print(colorize("   To include all your private repositories:", Style.WHITE + Style.BOLD))
            print(colorize("   1. Go to: https://github.com/settings/tokens", Style.CYAN))
            print(colorize("   2. Edit your token and change 'Repository access' to 'All repositories'", Style.CYAN))
            print(colorize("      OR generate a Classic Token (starts with ghp_) with the 'repo' scope.\n", Style.CYAN))

        # Convert date range to ISO 8601 in UTC for GitHub API
        since_utc_iso = self.start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        until_utc_iso = self.end_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        commits_found: list[CommitInfo] = []
        seen_shas = set()
        start_utc = self.start_dt.astimezone(timezone.utc)

        for i, repo in enumerate(repos, 1):
            name = repo.get("name", "")
            full_name = repo.get("full_name", name)
            is_private = repo.get("private", False)
            pushed_at_str = repo.get("pushed_at")

            # Filter specific or excluded repos
            if self.specific_repos and name.lower() not in self.specific_repos and full_name.lower() not in self.specific_repos:
                continue
            if self.exclude_repos and (name.lower() in self.exclude_repos or full_name.lower() in self.exclude_repos):
                continue

            # Optimization: Skip repos pushed earlier than start date
            if pushed_at_str:
                try:
                    pushed_dt = datetime.fromisoformat(pushed_at_str.replace("Z", "+00:00"))
                    if pushed_dt < start_utc:
                        continue
                except Exception:
                    pass

            vis_badge = colorize("[Private]", Style.YELLOW) if is_private else colorize("[Public]", Style.GRAY)
            status_prefix = f"[{i}/{len(repos)}] Checking {colorize(full_name, Style.BOLD)} {vis_badge}"
            sys.stdout.write(f"\r\033[K{status_prefix}...")
            sys.stdout.flush()

            owner = repo.get("owner", {}).get("login") or self.fallback_username
            try:
                repo_commits = self.client.get_commits(
                    owner=owner,
                    repo=name,
                    since_iso=since_utc_iso,
                    until_iso=until_utc_iso
                )
            except Exception as err:
                sys.stdout.write(f"\r\033[K{status_prefix} -> {colorize('Error: ' + str(err), Style.RED)}\n")
                continue

            if not repo_commits:
                continue

            # Filter commits authored by user
            matched_repo_commits = []
            for c in repo_commits:
                sha = c.get("sha")
                if sha in seen_shas:
                    continue

                # Check if merge commit and user requested skip
                msg = c.get("commit", {}).get("message", "")
                is_merge = msg.lower().startswith("merge branch") or msg.lower().startswith("merge pull request")
                if self.skip_merges and is_merge:
                    continue

                if self.is_commit_by_user(c, repo_owner=owner):
                    seen_shas.add(sha)
                    matched_repo_commits.append(c)

            if not matched_repo_commits:
                continue

            sys.stdout.write(f"\r\033[K{status_prefix} -> {colorize(f'{len(matched_repo_commits)} commits', Style.GREEN + Style.BOLD)}\n")
            sys.stdout.flush()

            # Process matched commits
            for c in matched_repo_commits:
                sha = c.get("sha")
                commit_obj = c.get("commit", {})
                author_obj = commit_obj.get("author", {})
                gh_author = c.get("author") or {}

                # Parse commit date & convert to local timezone
                date_str = author_obj.get("date")
                try:
                    commit_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    commit_dt_local = commit_dt.astimezone()
                except Exception:
                    commit_dt_local = datetime.now()

                # Detailed stats if requested
                stats = None
                if self.include_stats:
                    detail = self.client.get_commit_detail(owner, name, sha)
                    if detail and "stats" in detail:
                        files = detail.get("files", [])
                        stats = {
                            "additions": detail["stats"].get("additions", 0),
                            "deletions": detail["stats"].get("deletions", 0),
                            "total": detail["stats"].get("total", 0),
                            "files_count": len(files)
                        }

                commit_info = CommitInfo(
                    sha=sha,
                    repo_name=name,
                    repo_full_name=full_name,
                    repo_url=repo.get("html_url", f"https://github.com/{full_name}"),
                    message=commit_obj.get("message", ""),
                    author_name=author_obj.get("name", "Unknown"),
                    author_email=author_obj.get("email", ""),
                    author_login=gh_author.get("login"),
                    commit_dt_local=commit_dt_local,
                    commit_url=c.get("html_url", f"https://github.com/{full_name}/commit/{sha}"),
                    stats=stats
                )
                commits_found.append(commit_info)

        sys.stdout.write("\r\033[K")  # Clear scanning line
        return commits_found


# ---------------------------------------------------------------------------
# Local Git Repository Collector (Direct Disk Scanning)
# ---------------------------------------------------------------------------
class LocalGitCollector:
    """Discovers git repositories in local directories and collects commits using local git CLI."""
    IGNORE_DIRS = {
        ".git", "node_modules", "venv", ".venv", "env", ".env", "dist", "build",
        ".next", ".nuxt", "__pycache__", ".cache", "bin", "obj", "vendor"
    }

    def __init__(
        self,
        root_path: str,
        start_dt: datetime,
        end_dt: datetime,
        specific_repos: list[str] | None = None,
        exclude_repos: list[str] | None = None,
        include_stats: bool = False,
        all_authors: bool = False,
        skip_merges: bool = False,
        target_author: str | None = None
    ):
        self.root_path = os.path.abspath(root_path)
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.specific_repos = [r.lower() for r in (specific_repos or [])]
        self.exclude_repos = [r.lower() for r in (exclude_repos or [])]
        self.include_stats = include_stats
        self.all_authors = all_authors
        self.skip_merges = skip_merges
        self.target_author = target_author

        self.user_names = set()
        self.user_emails = set()
        if target_author:
            self.user_names.add(target_author.lower())
        else:
            git_name, git_email = get_local_git_config()
            if git_name:
                self.user_names.add(git_name.lower())
            if git_email:
                self.user_emails.add(git_email.lower())

    def find_git_repos(self, max_depth: int = 3) -> list[str]:
        """Finds git repositories within root_path up to max_depth."""
        repos = []
        root_depth = self.root_path.rstrip(os.sep).count(os.sep)

        for current_root, dirs, files in os.walk(self.root_path):
            current_depth = current_root.rstrip(os.sep).count(os.sep) - root_depth
            if current_depth > max_depth:
                dirs[:] = []
                continue

            # Remove ignored directories to prune walk
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]

            if ".git" in os.listdir(current_root) and os.path.isdir(os.path.join(current_root, ".git")):
                repos.append(current_root)
                # Don't recurse into subdirectories of an already found git repository
                dirs[:] = []

        return repos

    def collect(self) -> list[CommitInfo]:
        print(colorize(f"\n📂 Scanning local git repositories under: {self.root_path}...", Style.CYAN + Style.BOLD))
        repos = self.find_git_repos()
        print(f"   Found {colorize(str(len(repos)), Style.BOLD)} local repositories.\n")

        commits_found: list[CommitInfo] = []
        since_str = self.start_dt.strftime("%Y-%m-%d %H:%M:%S")
        until_str = self.end_dt.strftime("%Y-%m-%d %H:%M:%S")

        for repo_path in repos:
            repo_name = os.path.basename(repo_path)
            remote_url = ""
            repo_full_name = repo_name

            # Resolve Remote URL and full name
            try:
                res_url = subprocess.run(
                    ["git", "-C", repo_path, "config", "--get", "remote.origin.url"],
                    capture_output=True, text=True, check=False
                )
                if res_url.returncode == 0 and res_url.stdout.strip():
                    raw_url = res_url.stdout.strip()
                    match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", raw_url)
                    if match:
                        repo_full_name = f"{match.group(1)}/{match.group(2)}"
                        remote_url = f"https://github.com/{repo_full_name}"
                    else:
                        remote_url = raw_url
            except Exception:
                pass

            # Filter repos if specified
            if self.specific_repos and repo_name.lower() not in self.specific_repos and repo_full_name.lower() not in self.specific_repos:
                continue
            if self.exclude_repos and (repo_name.lower() in self.exclude_repos or repo_full_name.lower() in self.exclude_repos):
                continue

            # Query git log
            cmd = [
                "git", "-C", repo_path, "log",
                f"--since={since_str}",
                f"--until={until_str}",
                "--format=%H||%an||%ae||%aI||%s"
            ]
            if self.skip_merges:
                cmd.append("--no-merges")

            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode != 0 or not res.stdout.strip():
                    continue
            except Exception:
                continue

            lines = [l for l in res.stdout.strip().split("\n") if l.strip()]
            if not lines:
                continue

            matched_count = 0
            for line in lines:
                parts = line.split("||")
                if len(parts) < 5:
                    continue
                sha, author_name, author_email, iso_date, summary = parts[0], parts[1], parts[2], parts[3], parts[4]

                # Author match
                if not self.all_authors:
                    is_match = False
                    if author_email.lower() in self.user_emails:
                        is_match = True
                    elif author_name.lower() in self.user_names:
                        is_match = True
                    else:
                        for u in self.user_names:
                            clean_u = re.sub(r"[^a-zA-Z0-9]", "", u)
                            clean_author = re.sub(r"[^a-zA-Z0-9]", "", author_name)
                            if len(clean_u) >= 4 and (clean_u in clean_author or clean_author in clean_u):
                                is_match = True
                                break
                    if not is_match:
                        continue

                try:
                    commit_dt = datetime.fromisoformat(iso_date)
                    commit_dt_local = commit_dt.astimezone()
                except Exception:
                    commit_dt_local = datetime.now()

                stats = None
                if self.include_stats:
                    res_stat = subprocess.run(
                        ["git", "-C", repo_path, "log", "-1", "--shortstat", sha],
                        capture_output=True, text=True, check=False
                    )
                    if res_stat.returncode == 0:
                        m_add = re.search(r"(\d+) insertion", res_stat.stdout)
                        m_del = re.search(r"(\d+) deletion", res_stat.stdout)
                        m_files = re.search(r"(\d+) file", res_stat.stdout)
                        stats = {
                            "additions": int(m_add.group(1)) if m_add else 0,
                            "deletions": int(m_del.group(1)) if m_del else 0,
                            "total": (int(m_add.group(1)) if m_add else 0) + (int(m_del.group(1)) if m_del else 0),
                            "files_count": int(m_files.group(1)) if m_files else 1
                        }

                commit_url = f"{remote_url}/commit/{sha}" if remote_url else f"#{sha[:7]}"

                commit_info = CommitInfo(
                    sha=sha,
                    repo_name=repo_name,
                    repo_full_name=repo_full_name,
                    repo_url=remote_url or f"#{repo_name}",
                    message=summary,
                    author_name=author_name,
                    author_email=author_email,
                    author_login=None,
                    commit_dt_local=commit_dt_local,
                    commit_url=commit_url,
                    stats=stats
                )
                commits_found.append(commit_info)
                matched_count += 1

            if matched_count > 0:
                print(f"   📦 {colorize(repo_full_name, Style.YELLOW + Style.BOLD)} -> {colorize(str(matched_count) + ' commits', Style.GREEN + Style.BOLD)}")

        return commits_found


# ---------------------------------------------------------------------------
# PDF Browser Engine Helper
# ---------------------------------------------------------------------------
def find_browser_for_pdf() -> str | None:
    """Finds Microsoft Edge or Google Chrome executable for headless PDF generation."""
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser", "brave"):
        found = shutil.which(name)
        if found:
            return found

    return None


def export_html_to_pdf(html_path: str, pdf_path: str) -> bool:
    """Invokes headless Edge or Chrome to compile an HTML document into a publication-ready PDF."""
    browser_exe = find_browser_for_pdf()
    if not browser_exe:
        return False

    abs_html = os.path.abspath(html_path)
    abs_pdf = os.path.abspath(pdf_path)
    os.makedirs(os.path.dirname(abs_pdf), exist_ok=True)

    try:
        cmd = [
            browser_exe,
            "--headless",
            "--disable-gpu",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={abs_pdf}",
            abs_html
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return os.path.isfile(abs_pdf) and os.path.getsize(abs_pdf) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Humanized Work Report Engine & Categorizer
# ---------------------------------------------------------------------------
class HumanizedChange:
    """Processes raw git commit summaries into clean, human-readable action items with domain categorization."""
    def __init__(self, commit: CommitInfo):
        self.commit = commit
        self.raw_summary = commit.summary
        self.cleaned_title, self.category_key, self.category_title, self.icon = self._analyze(commit.summary)

    def _analyze(self, summary: str) -> tuple[str, str, str, str]:
        # Strip conventional commit prefixes (e.g., feat:, fix(ui):, chore:, etc.)
        cleaned = re.sub(
            r"^(feat|fix|refactor|perf|docs|test|chore|style|build|ci|sec)(\([^)]+\))?:\s*",
            "", summary, flags=re.IGNORECASE
        ).strip()

        # Strip project/ticket identifiers (e.g. [PROJ-123], JIRA-456:)
        cleaned = re.sub(r"^\[?[A-Z]{2,10}-\d+\]?[:\s]*", "", cleaned).strip()

        # Strip trailing PR identifiers (e.g. (#12), closes #45)
        cleaned = re.sub(r"\s*\((#\d+|closes #\d+)\)", "", cleaned).strip()

        # Capitalize first character
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
        else:
            cleaned = summary.strip()

        lower = summary.lower()

        # Domain Categorization
        if any(k in lower for k in ["rbac", "whitelist", "security", "nextauth", "permission", "jwt", "auth", "token", "session", "password"]):
            return cleaned, "security", "Security & Access Control", "🛡️"
        elif any(k in lower for k in ["google sheet", "meta graph", "graph api", "smo", "email worker", "webhook", "integration", "third-party", "slack", "stripe"]):
            return cleaned, "integrations", "External Integrations & Services", "🔌"
        elif any(k in lower for k in ["component", "sidebar", "navbar", "modal", "gallery", "frontend", "form", "view", "page", "dashboard", "demo", "button", "table", "layout"]):
            return cleaned, "ui", "UI / UX & Frontend Dashboards", "🎨"
        elif any(k in lower for k in ["api", "endpoint", "backend", "service", "model", "controller", "repository", "database", "query", "route"]):
            return cleaned, "backend", "Backend & API Architecture", "⚙️"
        elif any(k in lower for k in ["fix", "bug", "patch", "error", "hotfix", "issue", "resolve", "crash"]):
            return cleaned, "fixes", "Bug Fixes & Stability", "🐛"
        elif any(k in lower for k in ["refactor", "perf", "optimize", "speed", "cleanup", "restructure", "simplify"]):
            return cleaned, "refactor", "Performance & Refactoring", "⚡"
        else:
            return cleaned, "features", "Core Features & Capabilities", "🚀"


class WorkReportAnalyzer:
    """Analyzes a collection of commits to extract high-level highlights, categorized changes, and QA test checklists."""
    def __init__(self, commits: list[CommitInfo]):
        self.commits = commits
        self.human_changes: list[HumanizedChange] = []
        for c in commits:
            if c.is_merge:
                continue
            self.human_changes.append(HumanizedChange(c))

    def get_categorized_changes(self) -> dict[str, dict]:
        """Returns dict of categorized changes in presentation priority."""
        order = [
            ("features", "Core Features & Capabilities", "🚀"),
            ("security", "Security & Access Control", "🛡️"),
            ("integrations", "External Integrations & Services", "🔌"),
            ("ui", "UI / UX & Frontend Dashboards", "🎨"),
            ("backend", "Backend & API Architecture", "⚙️"),
            ("refactor", "Performance & Refactoring", "⚡"),
            ("fixes", "Bug Fixes & Stability", "🐛")
        ]
        result = {}
        for key, title, icon in order:
            matched = [ch for ch in self.human_changes if ch.category_key == key]
            if matched:
                result[key] = {
                    "title": title,
                    "icon": icon,
                    "items": matched
                }
        return result

    def generate_highlights(self) -> list[str]:
        """Synthesizes high-level executive highlights from the collection of changes."""
        highlights = []
        cat_map = self.get_categorized_changes()

        if "security" in cat_map:
            sec_items = [ch.cleaned_title for ch in cat_map["security"]["items"]]
            keywords = []
            if any("rbac" in s.lower() for s in sec_items): keywords.append("Role-Based Access Control (RBAC)")
            if any("whitelist" in s.lower() for s in sec_items): keywords.append("IP Whitelisting")
            if any("nextauth" in s.lower() or "auth" in s.lower() for s in sec_items): keywords.append("NextAuth authentication")
            if keywords:
                highlights.append(f"Security & Governance: Hardened system security with {', '.join(keywords)} across core services.")
            else:
                highlights.append(f"Security & Access Control: Delivered {len(sec_items)} security enhancements.")

        if "integrations" in cat_map:
            int_items = [ch.cleaned_title for ch in cat_map["integrations"]["items"]]
            keywords = []
            if any("google sheet" in s.lower() for s in int_items): keywords.append("Google Sheets API")
            if any("meta graph" in s.lower() or "smo" in s.lower() for s in int_items): keywords.append("Meta Graph API (Social Media Optimization)")
            if any("email worker" in s.lower() for s in int_items): keywords.append("Automated Email Workers")
            if keywords:
                highlights.append(f"External Integrations: Integrated {', '.join(keywords)} for automated workflows and data synchronization.")
            else:
                highlights.append(f"External Integrations: Shipped {len(int_items)} third-party integrations.")

        if "ui" in cat_map or "features" in cat_map:
            ui_items = [ch.cleaned_title for ch in (cat_map.get("ui", {}).get("items", []) + cat_map.get("features", {}).get("items", []))]
            keywords = []
            if any("demo" in s.lower() or "product" in s.lower() for s in ui_items): keywords.append("interactive product demo pages")
            if any("statement" in s.lower() or "report" in s.lower() for s in ui_items): keywords.append("item-wise financial statement reports")
            if any("distributor" in s.lower() or "map" in s.lower() for s in ui_items): keywords.append("distributor locator with map integration")
            if any("sidebar" in s.lower() for s in ui_items): keywords.append("role-aware admin navigation")
            if keywords:
                highlights.append(f"Frontend & Dashboards: Built {', '.join(keywords)}.")
            else:
                highlights.append(f"Product Delivery: Shipped {len(ui_items)} user interface components and features.")

        active_repos = sorted(list({c.repo_name for c in self.commits}))
        highlights.append(f"Delivery Velocity: Successfully completed {len(self.commits)} updates across {len(active_repos)} repositories.")

        return highlights

    def derive_qa_checklist(self) -> list[str]:
        """Derives actionable test/verification checklist items for QA and release validation."""
        test_items = []
        seen = set()

        def add(item: str):
            if item not in seen:
                seen.add(item)
                test_items.append(item)

        for ch in self.human_changes:
            text = ch.cleaned_title.lower()
            repo = ch.commit.repo_name

            if "rbac" in text or "role" in text:
                add(f"Verify Role-Based Access Control (RBAC): test user roles and department boundaries in [{repo}] to ensure restricted actions are blocked.")
            if "whitelist" in text or "ip" in text:
                add(f"Test IP Whitelist login protection in [{repo}]: confirm authorized IPs log in successfully and unauthorized IPs receive 403 Forbidden.")
            if "nextauth" in text or "auth" in text:
                add(f"Verify NextAuth authentication flow in [{repo}]: test session creation, token persistence, and logout behavior.")
            if "google sheet" in text:
                add(f"Test Google Sheets automated sync in [{repo}]: verify data rows synchronize accurately upon form or lead submission.")
            if "meta graph" in text or "smo" in text or "social media" in text:
                add(f"Test Meta Graph API integration in [{repo}]: verify social media scheduling, token refresh, and analytics metrics.")
            if "email worker" in text or "email" in text:
                add(f"Test background email worker in [{repo}]: ensure confirmation and notification emails are dispatched reliably.")
            if "multi-pet" in text or "interactive" in text or "demo" in text:
                add(f"Verify interactive demo page in [{repo}]: test multi-pet configuration switching and media gallery responsiveness.")
            if "map" in text or "distributor" in text:
                add(f"Test distributor locator page in [{repo}]: verify interactive map rendering and application management API.")
            if "statement report" in text or "summary reporting" in text or "statement" in text:
                add(f"Verify financial statement and summary report pages in [{repo}]: test date filters and server aggregation accuracy.")
            if "sidebar" in text or "navigation" in text:
                add(f"Validate AdminSidebar in [{repo}]: verify role-based navigation links and live counter badges.")
            if "contact form" in text or "lead" in text:
                add(f"Test contact/lead submission form in [{repo}]: test validation errors, successful submit, and thank you page redirect.")
            if ch.category_key == "fixes":
                add(f"Perform regression testing on bug fix: '{ch.cleaned_title}' in [{repo}].")

        if len(test_items) < 3 and self.human_changes:
            for ch in self.human_changes[:4]:
                add(f"Verify functional end-to-end workflow for: '{ch.cleaned_title}' in [{ch.commit.repo_name}].")

        return test_items


# ---------------------------------------------------------------------------
# Report Formatter & Exporter
# ---------------------------------------------------------------------------
class ReportGenerator:
    def __init__(
        self,
        commits: list[CommitInfo],
        start_dt: datetime,
        end_dt: datetime,
        user_identity: str | None = None
    ):
        self.commits = commits
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.user_identity = user_identity or "Developer"
        self.analyzer = WorkReportAnalyzer(commits)

    def group_by_day(self, reverse: bool = False) -> dict[str, dict[str, list[CommitInfo]]]:
        """
        Groups commits by date string (YYYY-MM-DD), then by repository.
        Returns: { '2026-10-15': { 'owner/repo': [commit1, commit2] } }
        """
        sorted_commits = sorted(self.commits, key=lambda c: c.commit_dt_local, reverse=reverse)

        grouped: dict[str, dict[str, list[CommitInfo]]] = {}
        for c in sorted_commits:
            day_key = c.day_str
            if day_key not in grouped:
                grouped[day_key] = {}
            if c.repo_full_name not in grouped[day_key]:
                grouped[day_key][c.repo_full_name] = []
            grouped[day_key][c.repo_full_name].append(c)

        return grouped

    def print_terminal_report(self, reverse: bool = False):
        """Prints a rich, formatted summary and day-wise timeline directly to the console."""
        grouped = self.group_by_day(reverse=reverse)
        total_commits = len(self.commits)
        active_repos = sorted(list({c.repo_full_name for c in self.commits}))
        active_days = len(grouped)

        start_str = self.start_dt.strftime("%b %d, %Y")
        end_str = self.end_dt.strftime("%b %d, %Y")

        # Header Box
        border = "═" * 74
        print("\n" + colorize(border, Style.CYAN))
        print(colorize("  📊 WORK PROGRESS & RELEASE VERIFICATION REPORT", Style.CYAN + Style.BOLD))
        print(colorize(f"  📅 Period: {start_str}  →  {end_str}", Style.WHITE))
        print(colorize(border, Style.CYAN))
        print(f"  👤 Author:        {colorize(self.user_identity, Style.BOLD)}")
        print(f"  🚀 Total Updates: {colorize(str(total_commits), Style.GREEN + Style.BOLD)}")
        print(f"  📦 Active Repos:  {colorize(str(len(active_repos)), Style.YELLOW + Style.BOLD)}")
        print(f"  🗓️  Active Days:   {colorize(str(active_days), Style.MAGENTA + Style.BOLD)}")

        if not self.commits:
            print(colorize("\n  No commits found within this date range.\n", Style.YELLOW))
            print(colorize(border, Style.CYAN) + "\n")
            return

        # Executive Highlights
        highlights = self.analyzer.generate_highlights()
        if highlights:
            print(colorize("\n🎯 EXECUTIVE HIGHLIGHTS & MILESTONES:", Style.BOLD + Style.UNDERLINE))
            for h in highlights:
                print(f"   • {colorize(h, Style.WHITE)}")

        # Humanized "What Changed & What Was Updated"
        categorized = self.analyzer.get_categorized_changes()
        if categorized:
            print(colorize("\n🚀 WHAT CHANGED & WHAT WAS UPDATED:", Style.BOLD + Style.UNDERLINE))
            for cat_key, cat_data in categorized.items():
                items = cat_data["items"]
                print(f"\n   {colorize(cat_data['icon'] + ' ' + cat_data['title'], Style.CYAN + Style.BOLD)} ({len(items)} update{'s' if len(items) != 1 else ''})")
                for it in items:
                    repo_badge = colorize(f"[{it.commit.repo_name}]", Style.YELLOW)
                    sha_badge = colorize(f"#{it.commit.short_sha}", Style.GRAY)
                    print(f"      • {repo_badge} {it.cleaned_title} {sha_badge}")

        # QA & Test Verification Checklist
        qa_checklist = self.analyzer.derive_qa_checklist()
        if qa_checklist:
            print(colorize("\n🧪 QA & TEST VERIFICATION CHECKLIST (WHAT TO TEST):", Style.BOLD + Style.UNDERLINE))
            for t in qa_checklist:
                print(f"   [ ] {colorize(t, Style.GREEN)}")

        # Day-by-Day Reference Log
        print(colorize("\n🗓️  CHRONOLOGICAL DAY-WISE REFERENCE LOG:\n", Style.BOLD + Style.UNDERLINE))

        for day_str, repos_dict in grouped.items():
            first_commit = next(iter(next(iter(repos_dict.values()))))
            weekday = first_commit.weekday
            day_total = sum(len(clist) for clist in repos_dict.values())

            # Day Header
            print(colorize(f"📅 {day_str} ({weekday})", Style.CYAN + Style.BOLD) +
                  colorize(f" — {day_total} commit{'s' if day_total != 1 else ''}", Style.DIM))

            for repo_name, commit_list in repos_dict.items():
                print(f"   📦 {colorize(repo_name, Style.YELLOW + Style.BOLD)} ({len(commit_list)})")
                for c in commit_list:
                    time_badge = colorize(f"[{c.time_str}]", Style.GRAY)
                    sha_badge = colorize(c.short_sha, Style.MAGENTA)

                    tag = ""
                    if c.is_merge:
                        tag = colorize("[merge] ", Style.GRAY)

                    stats_str = ""
                    if c.stats:
                        add = colorize(f"+{c.stats.get('additions', 0)}", Style.GREEN)
                        dels = colorize(f"-{c.stats.get('deletions', 0)}", Style.RED)
                        files = c.stats.get("files_count", 0)
                        stats_str = f" {Style.DIM}({add}, {dels} in {files} files){Style.RESET}"

                    print(f"      • {time_badge} {sha_badge} {tag}{c.summary}{stats_str}")

            print()

        # Repository Summary Table
        print(colorize("📦 REPOSITORY ACTIVITY SUMMARY:", Style.BOLD + Style.UNDERLINE))
        repo_counts: dict[str, int] = {}
        for c in self.commits:
            repo_counts[c.repo_full_name] = repo_counts.get(c.repo_full_name, 0) + 1

        for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
            bar = "█" * min(30, max(1, int((count / total_commits) * 30)))
            print(f"   {repo:<40} {count:>3} commits  {colorize(bar, Style.GREEN)}")

        print("\n" + colorize(border, Style.CYAN) + "\n")

    def generate_markdown(self, reverse: bool = False) -> str:
        """Generates comprehensive, human-readable GitHub Flavored Markdown report string."""
        grouped = self.group_by_day(reverse=reverse)
        total_commits = len(self.commits)
        active_repos = sorted(list({c.repo_full_name for c in self.commits}))
        active_days = len(grouped)

        start_str = self.start_dt.strftime("%Y-%m-%d")
        end_str = self.end_dt.strftime("%Y-%m-%d")

        md = []
        md.append("# 📊 Work Progress & Release Verification Report")
        md.append(f"**Period:** `{start_str}` to `{end_str}` | **Author:** `{self.user_identity}` | **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
        md.append("")

        # Executive Summary & Milestones
        highlights = self.analyzer.generate_highlights()
        md.append("## 🎯 Executive Summary & Milestones")
        md.append("")
        if highlights:
            for h in highlights:
                md.append(f"- **{h.split(':', 1)[0]}:** {h.split(':', 1)[1].strip() if ':' in h else h}")
        else:
            md.append("> *No work activity recorded in this period.*")
        md.append("")

        # Key Metrics Table
        md.append("### 📈 Key Metrics")
        md.append("")
        md.append("| Metric | Value |")
        md.append("| :--- | :--- |")
        md.append(f"| **Total Deliverables** | **{total_commits}** |")
        md.append(f"| **Active Repositories** | **{len(active_repos)}** |")
        md.append(f"| **Active Working Days** | **{active_days}** |")

        # Stats total
        total_add = sum(c.stats.get("additions", 0) for c in self.commits if c.stats)
        total_del = sum(c.stats.get("deletions", 0) for c in self.commits if c.stats)
        if total_add or total_del:
            md.append(f"| **Code Volume Changes** | `+{total_add}` additions, `-{total_del}` deletions |")

        md.append("")
        md.append("---")
        md.append("")

        # What Changed & What Was Updated
        md.append("## 🚀 What Changed & What Was Updated")
        md.append("")
        categorized = self.analyzer.get_categorized_changes()

        if not categorized:
            md.append("> *No direct work commits found.*")
        else:
            for cat_key, cat_data in categorized.items():
                items = cat_data["items"]
                md.append(f"### {cat_data['icon']} {cat_data['title']} ({len(items)} update{'s' if len(items) != 1 else ''})")
                md.append("")
                for it in items:
                    repo_link = f"[`{it.commit.repo_name}`]({it.commit.repo_url})"
                    commit_link = f"[`{it.commit.short_sha}`]({it.commit.commit_url})"
                    md.append(f"- {repo_link} &mdash; **{it.cleaned_title}** ({commit_link})")
                md.append("")

        md.append("---")
        md.append("")

        # QA & Test Verification Checklist
        qa_checklist = self.analyzer.derive_qa_checklist()
        md.append("## 🧪 QA & Test Verification Checklist (What to Test)")
        md.append("")
        if qa_checklist:
            for t in qa_checklist:
                md.append(f"- [ ] {t}")
        else:
            md.append("- [ ] Verify general application workflow and test for regressions.")
        md.append("")

        md.append("---")
        md.append("")

        # Repositories Table
        md.append("## 📦 Repositories Overview")
        md.append("")
        md.append("| Repository | Updates | Direct Link |")
        md.append("| :--- | :---: | :--- |")
        repo_counts: dict[str, int] = {}
        repo_urls: dict[str, str] = {}
        for c in self.commits:
            repo_counts[c.repo_full_name] = repo_counts.get(c.repo_full_name, 0) + 1
            repo_urls[c.repo_full_name] = c.repo_url

        for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
            url = repo_urls.get(repo, "#")
            md.append(f"| [`{repo}`]({url}) | **{count}** | [Open on GitHub]({url}) |")

        md.append("")
        md.append("---")
        md.append("")

        # Chronological Work Log (Reference)
        md.append("## 🗓️ Chronological Work Log (Reference)")
        md.append("")

        for day_str, repos_dict in grouped.items():
            first_commit = next(iter(next(iter(repos_dict.values()))))
            weekday = first_commit.weekday
            day_total = sum(len(clist) for clist in repos_dict.values())

            md.append(f"### 📅 {day_str} ({weekday}) &mdash; {day_total} Commit{'s' if day_total != 1 else ''}")
            md.append("")

            for repo_name, commit_list in repos_dict.items():
                first_c = commit_list[0]
                md.append(f"#### 📦 [{repo_name}]({first_c.repo_url}) ({len(commit_list)})")
                md.append("")

                for c in commit_list:
                    stats_badge = ""
                    if c.stats:
                        add = c.stats.get("additions", 0)
                        dels = c.stats.get("deletions", 0)
                        files = c.stats.get("files_count", 0)
                        stats_badge = f" *(+{add}, -{dels} in {files} files)*"

                    merge_badge = " `[merge]`" if c.is_merge else ""
                    md.append(f"- **`{c.time_str}`** [`{c.short_sha}`]({c.commit_url}){merge_badge} &mdash; {c.summary}{stats_badge}")

                    if c.body:
                        quoted_body = "\n".join([f"  > {line}" for line in c.body.split("\n") if line.strip()])
                        if quoted_body:
                            md.append(f"{quoted_body}")

                md.append("")

            md.append("---")
            md.append("")

        md.append(f"\n*Report generated by `reportingscript.py` on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(md)

    def generate_text_doc(self, reverse: bool = False) -> str:
        """Generates clean plain-text test / executive document format."""
        grouped = self.group_by_day(reverse=reverse)
        total_commits = len(self.commits)
        active_repos = sorted(list({c.repo_name for c in self.commits}))
        active_days = len(grouped)

        start_str = self.start_dt.strftime("%Y-%m-%d")
        end_str = self.end_dt.strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = []
        bar = "=" * 78
        sub_bar = "-" * 78

        lines.append(bar)
        lines.append("WORK PROGRESS & TEST VERIFICATION REPORT")
        lines.append(f"Period: {start_str} to {end_str} | Author: {self.user_identity}")
        lines.append(f"Generated: {now_str}")
        lines.append(bar)
        lines.append("")

        lines.append("[EXECUTIVE SUMMARY & MILESTONES]")
        highlights = self.analyzer.generate_highlights()
        for h in highlights:
            lines.append(f"• {h}")
        lines.append("")

        lines.append("[KEY METRICS]")
        lines.append(f"- Total Deliverables:    {total_commits}")
        lines.append(f"- Active Repositories:   {len(active_repos)}")
        lines.append(f"- Active Days Worked:    {active_days}")
        total_add = sum(c.stats.get("additions", 0) for c in self.commits if c.stats)
        total_del = sum(c.stats.get("deletions", 0) for c in self.commits if c.stats)
        if total_add or total_del:
            lines.append(f"- Code Changes Volume:   +{total_add} additions, -{total_del} deletions")
        lines.append("")

        lines.append("[WHAT CHANGED & WHAT WAS UPDATED]")
        lines.append(sub_bar)
        categorized = self.analyzer.get_categorized_changes()
        idx = 1
        for cat_key, cat_data in categorized.items():
            items = cat_data["items"]
            lines.append(f"{idx}. {cat_data['title'].upper()} ({len(items)} updates):")
            for it in items:
                lines.append(f"   * [{it.commit.repo_name}] {it.cleaned_title} (#{it.commit.short_sha})")
            lines.append("")
            idx += 1

        lines.append("[QA & TEST VERIFICATION CHECKLIST (WHAT TO TEST)]")
        lines.append(sub_bar)
        qa_checklist = self.analyzer.derive_qa_checklist()
        for t in qa_checklist:
            lines.append(f"[ ] {t}")
        lines.append("")

        lines.append("[ACTIVE REPOSITORIES OVERVIEW]")
        lines.append(sub_bar)
        repo_counts: dict[str, int] = {}
        for c in self.commits:
            repo_counts[c.repo_full_name] = repo_counts.get(c.repo_full_name, 0) + 1
        for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"* {repo:<40} {count:>3} updates")
        lines.append("")
        lines.append(bar)
        lines.append(f"End of Report - Generated by reportingscript.py")

        return "\n".join(lines)

    def generate_html(self, reverse: bool = False) -> str:
        """Generates complete, self-contained executive HTML report with responsive styling and print stylesheet."""
        grouped = self.group_by_day(reverse=reverse)
        total_commits = len(self.commits)
        active_repos = sorted(list({c.repo_full_name for c in self.commits}))
        active_days = len(grouped)

        start_str = self.start_dt.strftime("%b %d, %Y")
        end_str = self.end_dt.strftime("%b %d, %Y")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        highlights = self.analyzer.generate_highlights()
        categorized = self.analyzer.get_categorized_changes()
        qa_checklist = self.analyzer.derive_qa_checklist()

        sec_count = len(categorized.get("security", {}).get("items", []))
        feat_count = len(categorized.get("features", {}).get("items", [])) + len(categorized.get("ui", {}).get("items", []))
        int_count = len(categorized.get("integrations", {}).get("items", []))

        html_parts = []
        html_parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Work Progress & Verification Report ({start_str} to {end_str})</title>
  <style>
    :root {{
      --primary: #2563eb;
      --primary-dark: #1d4ed8;
      --slate-900: #0f172a;
      --slate-800: #1e293b;
      --slate-700: #334155;
      --slate-600: #475569;
      --slate-500: #64748b;
      --slate-200: #e2e8f0;
      --slate-100: #f1f5f9;
      --slate-50: #f8fafc;
      --green-600: #059669;
      --indigo-600: #4f46e5;
      --amber-600: #d97706;
      --sky-600: #0284c7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--slate-50);
      color: var(--slate-900);
      line-height: 1.5;
      padding: 24px;
      -webkit-font-smoothing: antialiased;
    }}
    .container {{
      max-width: 1040px;
      margin: 0 auto;
    }}
    .top-bar {{
      display: flex;
      justify-content: flex-end;
      gap: 12px;
      margin-bottom: 16px;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      font-size: 14px;
      font-weight: 600;
      border-radius: 6px;
      border: 1px solid var(--slate-200);
      background: white;
      color: var(--slate-700);
      cursor: pointer;
      box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      transition: all 0.15s ease;
    }}
    .btn:hover {{
      background: var(--slate-100);
      color: var(--slate-900);
    }}
    .btn-primary {{
      background: var(--primary);
      border-color: var(--primary-dark);
      color: white;
    }}
    .btn-primary:hover {{
      background: var(--primary-dark);
    }}
    .header-card {{
      background: linear-gradient(135deg, var(--slate-900) 0%, var(--slate-800) 100%);
      color: white;
      border-radius: 12px;
      padding: 28px 32px;
      margin-bottom: 24px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.15);
    }}
    .header-title {{
      font-size: 26px;
      font-weight: 700;
      letter-spacing: -0.02em;
      margin-bottom: 8px;
    }}
    .header-sub {{
      font-size: 14.5px;
      color: #94a3b8;
      display: flex;
      flex-wrap: wrap;
      gap: 18px;
      align-items: center;
    }}
    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .stat-card {{
      background: white;
      border: 1px solid var(--slate-200);
      border-radius: 10px;
      padding: 16px 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }}
    .stat-label {{
      font-size: 12.5px;
      color: var(--slate-500);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      margin-bottom: 4px;
    }}
    .stat-val {{
      font-size: 26px;
      font-weight: 700;
      color: var(--slate-900);
      letter-spacing: -0.02em;
    }}
    .card {{
      background: white;
      border: 1px solid var(--slate-200);
      border-radius: 10px;
      padding: 22px 26px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.03);
    }}
    .card-title {{
      font-size: 18px;
      font-weight: 700;
      color: var(--slate-900);
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
      border-bottom: 1px solid var(--slate-100);
      padding-bottom: 10px;
    }}
    .highlight-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .highlight-item {{
      position: relative;
      padding-left: 20px;
      font-size: 14.5px;
      color: var(--slate-700);
    }}
    .highlight-item::before {{
      content: "•";
      position: absolute;
      left: 4px;
      color: var(--primary);
      font-size: 22px;
      line-height: 1;
      top: -2px;
    }}
    .cat-group {{
      margin-bottom: 20px;
    }}
    .cat-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--slate-200);
    }}
    .cat-header-title {{
      font-size: 15px;
      font-weight: 700;
      color: var(--slate-800);
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .cat-count {{
      font-size: 12px;
      background: var(--slate-100);
      color: var(--slate-600);
      padding: 2px 8px;
      border-radius: 9999px;
      font-weight: 600;
    }}
    .change-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .change-item {{
      font-size: 14px;
      color: var(--slate-800);
      display: flex;
      align-items: baseline;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 6px;
      background: var(--slate-50);
      border: 1px solid rgba(226, 232, 240, 0.8);
    }}
    .repo-pill {{
      font-size: 11.5px;
      font-weight: 600;
      color: #1e40af;
      background: #dbeafe;
      padding: 2px 8px;
      border-radius: 4px;
      white-space: nowrap;
      text-decoration: none;
    }}
    .commit-link {{
      margin-left: auto;
      font-size: 11px;
      color: var(--slate-500);
      text-decoration: none;
      font-family: monospace;
      padding: 2px 6px;
      background: white;
      border: 1px solid var(--slate-200);
      border-radius: 4px;
      white-space: nowrap;
    }}
    .commit-link:hover {{
      color: var(--primary);
      border-color: var(--primary);
    }}
    .qa-list {{
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .qa-item {{
      display: flex;
      align-items: flex-start;
      gap: 10px;
      font-size: 14px;
      color: var(--slate-800);
      background: #fbfcfd;
      padding: 9px 12px;
      border-radius: 6px;
      border: 1px solid var(--slate-200);
    }}
    .qa-checkbox {{
      margin-top: 3px;
      cursor: pointer;
    }}
    .table-container {{
      overflow-x: auto;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13.5px;
    }}
    th {{
      text-align: left;
      padding: 10px 12px;
      background: var(--slate-100);
      color: var(--slate-700);
      font-weight: 600;
      border-bottom: 2px solid var(--slate-200);
    }}
    td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--slate-100);
      color: var(--slate-800);
    }}
    tr:hover td {{
      background: var(--slate-50);
    }}
    details {{
      background: white;
      border: 1px solid var(--slate-200);
      border-radius: 8px;
      padding: 12px 16px;
      margin-bottom: 10px;
    }}
    details summary {{
      cursor: pointer;
      font-weight: 600;
      font-size: 14px;
      color: var(--slate-700);
    }}
    .details-content {{
      margin-top: 10px;
      padding-top: 10px;
      border-top: 1px solid var(--slate-100);
      font-size: 13px;
    }}
    @media print {{
      @page {{
        margin: 12mm 10mm;
        size: A4 portrait;
      }}
      body {{
        background: white !important;
        padding: 0 !important;
        font-size: 10pt !important;
        color: #000 !important;
      }}
      .no-print {{
        display: none !important;
      }}
      .container {{
        max-width: 100% !important;
      }}
      .header-card {{
        background: #0f172a !important;
        color: white !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
        box-shadow: none !important;
        padding: 18px 20px !important;
        margin-bottom: 14px !important;
      }}
      .card, .stat-card {{
        box-shadow: none !important;
        border: 1px solid #cbd5e1 !important;
        break-inside: avoid;
        page-break-inside: avoid;
        margin-bottom: 14px !important;
        padding: 14px 18px !important;
      }}
      .change-item, .qa-item {{
        background: #f8fafc !important;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="top-bar no-print">
      <button onclick="window.print()" class="btn btn-primary">🖨️ Print / Save as PDF</button>
    </div>

    <!-- Header Card -->
    <div class="header-card">
      <h1 class="header-title">📊 Work Progress & Release Verification Report</h1>
      <div class="header-sub">
        <span>📅 <strong>Period:</strong> {start_str} &mdash; {end_str}</span>
        <span>👤 <strong>Author:</strong> {html.escape(self.user_identity)}</span>
        <span>⏱️ <strong>Generated:</strong> {now_str}</span>
      </div>
    </div>

    <!-- KPI Stats -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Deliverables</div>
        <div class="stat-val">{total_commits}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Active Repositories</div>
        <div class="stat-val">{len(active_repos)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Security & Access</div>
        <div class="stat-val" style="color: var(--indigo-600)">{sec_count}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Features & UI Dashboards</div>
        <div class="stat-val" style="color: var(--sky-600)">{feat_count}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">External Integrations</div>
        <div class="stat-val" style="color: var(--amber-600)">{int_count}</div>
      </div>
    </div>

    <!-- Executive Highlights -->
    <div class="card">
      <h2 class="card-title">🎯 Executive Summary & Milestones</h2>
      <ul class="highlight-list">
""")

        if highlights:
            for h in highlights:
                html_parts.append(f'        <li class="highlight-item">{html.escape(h)}</li>')
        else:
            html_parts.append('        <li class="highlight-item">No commits recorded in this date range.</li>')

        html_parts.append("""      </ul>
    </div>

    <!-- What Changed & What Was Updated -->
    <div class="card">
      <h2 class="card-title">🚀 What Changed & What Was Updated</h2>
""")

        if not categorized:
            html_parts.append('      <p style="color: var(--slate-500); font-size: 14px;">No direct updates found.</p>')
        else:
            for cat_key, cat_data in categorized.items():
                html_parts.append(f"""
      <div class="cat-group">
        <div class="cat-header">
          <span class="cat-header-title">{cat_data['icon']} {html.escape(cat_data['title'])}</span>
          <span class="cat-count">{len(cat_data['items'])} update{'s' if len(cat_data['items']) != 1 else ''}</span>
        </div>
        <ul class="change-list">""")
                for item in cat_data['items']:
                    repo_name = html.escape(item.commit.repo_name)
                    title = html.escape(item.cleaned_title)
                    sha = html.escape(item.commit.short_sha)
                    url = html.escape(item.commit.commit_url)
                    html_parts.append(f"""          <li class="change-item">
            <span class="repo-pill">{repo_name}</span>
            <span>{title}</span>
            <a href="{url}" target="_blank" class="commit-link" title="Open commit on GitHub">{sha}</a>
          </li>""")
                html_parts.append("""        </ul>
      </div>""")

        html_parts.append("""    </div>

    <!-- QA & Test Verification Checklist -->
    <div class="card">
      <h2 class="card-title">🧪 QA & Test Verification Checklist (What to Test)</h2>
      <ul class="qa-list">
""")

        if qa_checklist:
            for t in qa_checklist:
                esc_t = html.escape(t)
                html_parts.append(f"""        <li class="qa-item">
          <input type="checkbox" class="qa-checkbox">
          <span>{esc_t}</span>
        </li>""")
        else:
            html_parts.append("""        <li class="qa-item">
          <input type="checkbox" class="qa-checkbox">
          <span>Perform standard regression verification on modified components.</span>
        </li>""")

        html_parts.append("""      </ul>
    </div>

    <!-- Repositories Overview -->
    <div class="card">
      <h2 class="card-title">📦 Active Repositories Overview</h2>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Repository</th>
              <th>Total Updates</th>
              <th>Link</th>
            </tr>
          </thead>
          <tbody>
""")

        repo_counts: dict[str, int] = {}
        repo_urls: dict[str, str] = {}
        for c in self.commits:
            repo_counts[c.repo_full_name] = repo_counts.get(c.repo_full_name, 0) + 1
            repo_urls[c.repo_full_name] = c.repo_url

        for repo, count in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
            url = repo_urls.get(repo, "#")
            html_parts.append(f"""            <tr>
              <td><strong>{html.escape(repo)}</strong></td>
              <td>{count} updates</td>
              <td><a href="{html.escape(url)}" target="_blank" class="repo-pill">Open GitHub</a></td>
            </tr>""")

        html_parts.append("""          </tbody>
        </table>
      </div>
    </div>

    <!-- Chronological Work Log (Reference) -->
    <div class="card no-print">
      <h2 class="card-title">🗓️ Chronological Activity Log (Audit Reference)</h2>
""")

        for day_str, repos_dict in grouped.items():
            first_commit = next(iter(next(iter(repos_dict.values()))))
            weekday = first_commit.weekday
            day_total = sum(len(clist) for clist in repos_dict.values())

            html_parts.append(f"""      <details>
        <summary>📅 {day_str} ({weekday}) &mdash; {day_total} updates</summary>
        <div class="details-content">""")

            for repo_name, commit_list in repos_dict.items():
                html_parts.append(f"""          <div style="margin-bottom: 10px;">
            <strong style="color: var(--slate-800);">📦 {html.escape(repo_name)}</strong>
            <ul style="list-style: none; margin-top: 6px; padding-left: 12px;">""")
                for c in commit_list:
                    tag = " [merge]" if c.is_merge else ""
                    html_parts.append(f"""              <li style="margin-bottom: 4px; font-size: 13px; color: var(--slate-700);">
                <span style="color: var(--slate-500); font-family: monospace;">[{c.time_str}]</span>
                <a href="{html.escape(c.commit_url)}" target="_blank" style="color: var(--primary); text-decoration: none; font-family: monospace;">{c.short_sha}</a>{tag} &mdash; {html.escape(c.summary)}
              </li>""")
                html_parts.append("""            </ul>
          </div>""")

            html_parts.append("""        </div>
      </details>""")

        html_parts.append("""    </div>

    <div style="text-align: center; color: var(--slate-500); font-size: 12px; margin-top: 32px;" class="no-print">
      Report generated by <strong>reportingscript.py</strong>
    </div>
  </div>
</body>
</html>
""")

        return "\n".join(html_parts)

    def save_markdown(self, filepath: str, reverse: bool = False) -> str:
        """Saves generated markdown report to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        content = self.generate_markdown(reverse=reverse)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.abspath(filepath)

    def save_text_doc(self, filepath: str, reverse: bool = False) -> str:
        """Saves plain text / test document format to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        content = self.generate_text_doc(reverse=reverse)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.abspath(filepath)

    def save_html(self, filepath: str, reverse: bool = False) -> str:
        """Saves interactive styled HTML report to disk."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        content = self.generate_html(reverse=reverse)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return os.path.abspath(filepath)

    def save_pdf(self, filepath: str, reverse: bool = False) -> str | None:
        """Compiles styled HTML report to publication-ready PDF using headless Edge/Chrome."""
        html_temp_path = filepath.rsplit(".", 1)[0] + ".html"
        if not os.path.isfile(html_temp_path):
            self.save_html(html_temp_path, reverse=reverse)

        ok = export_html_to_pdf(html_temp_path, filepath)
        if ok:
            return os.path.abspath(filepath)
        return None

    def save_json(self, filepath: str) -> str:
        """Exports raw report data to JSON format."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        data = {
            "report_period": {
                "start": self.start_dt.isoformat(),
                "end": self.end_dt.isoformat()
            },
            "user": self.user_identity,
            "total_commits": len(self.commits),
            "executive_highlights": self.analyzer.generate_highlights(),
            "qa_test_checklist": self.analyzer.derive_qa_checklist(),
            "commits": [
                {
                    "sha": c.sha,
                    "short_sha": c.short_sha,
                    "repository": c.repo_full_name,
                    "date": c.commit_dt_local.isoformat(),
                    "day": c.day_str,
                    "weekday": c.weekday,
                    "time": c.time_str,
                    "is_merge": c.is_merge,
                    "summary": c.summary,
                    "body": c.body,
                    "url": c.commit_url,
                    "stats": c.stats
                }
                for c in self.commits
            ]
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return os.path.abspath(filepath)


# ---------------------------------------------------------------------------
# Interactive Prompts
# ---------------------------------------------------------------------------
def prompt_for_token() -> str:
    """Interactively prompts user for GitHub Token with guidance."""
    print("\n" + colorize("🔐 GitHub Personal Access Token Required for Private Repos", Style.CYAN + Style.BOLD))
    print("A GitHub token is needed to access your private repositories and avoid strict rate limits.")
    print(colorize("Create a token with 'repo' scope at: https://github.com/settings/tokens", Style.GRAY))
    print()

    token = input(colorize("Enter your GitHub Personal Access Token (or press Enter to skip): ", Style.YELLOW)).strip()
    if token:
        save_choice = input(colorize("Would you like to save this token in a local .env file? (y/n) [default: y]: ", Style.CYAN)).strip().lower()
        if save_choice in ("", "y", "yes"):
            try:
                env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
                with open(env_path, "a", encoding="utf-8") as f:
                    f.write(f"\nGITHUB_TOKEN={token}\n")
                print(colorize(f"✔ Token saved to {env_path}", Style.GREEN))
            except Exception as e:
                print(colorize(f"Warning: Could not save .env: {e}", Style.YELLOW))
    return token


def prompt_for_dates() -> tuple[str, str]:
    """Prompts for start and end dates with intelligent defaults."""
    today_str = date.today().strftime("%Y-%m-%d")
    default_start = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

    print(colorize("\n📅 Specify Date Range for the Report:", Style.BOLD))
    print("Format: YYYY-MM-DD or keywords (today, yesterday, 7d, 14d, 30d, this-week, this-month)")

    start_in = input(f"Enter START date [default: {colorize(default_start, Style.CYAN)} (7 days ago)]: ").strip()
    if not start_in:
        start_in = default_start

    end_in = input(f"Enter END date   [default: {colorize(today_str, Style.CYAN)} (today)]: ").strip()
    if not end_in:
        end_in = today_str

    return start_in, end_in


# ---------------------------------------------------------------------------
# CLI Argument Parser & Main Entry Point
# ---------------------------------------------------------------------------
def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch GitHub commits across public & private repositories and generate human-readable work & test reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (generates Markdown, HTML, and publication-ready PDF):
  python reportingscript.py

  # Specific date range:
  python reportingscript.py --start 2026-10-01 --end 2026-10-15

  # Relative keywords:
  python reportingscript.py --start 7d --end today
  python reportingscript.py --start this-week

  # Generate all formats (Markdown, HTML, PDF, Text Doc, JSON):
  python reportingscript.py --start 14d --all-formats

  # Filter specific repositories:
  python reportingscript.py --start 7d --repo rdgboos --repo start_tag
        """
    )

    parser.add_argument("-s", "--start", dest="start_date", help="Start date (YYYY-MM-DD, today, yesterday, 7d, 14d, 30d, this-week, this-month)")
    parser.add_argument("-e", "--end", dest="end_date", help="End date (YYYY-MM-DD, today, etc.)")
    parser.add_argument("-t", "--token", dest="token", help="GitHub Personal Access Token (defaults to GITHUB_TOKEN or GH_TOKEN env var)")
    parser.add_argument("-a", "--author", dest="author", help="Filter commits by specific author username or email (defaults to authenticated user / git config)")
    parser.add_argument("--all-authors", action="store_true", help="Include commits by all authors across repositories")
    parser.add_argument("-l", "--local", dest="local_dir", help="Scan local directory for git repositories instead of (or in addition to) GitHub API (e.g. D:\\projects)")
    parser.add_argument("--skip-merges", "--no-merges", action="store_true", help="Exclude merge commits from report")
    parser.add_argument("-o", "--output", dest="output_file", help="Custom base path for output report files")
    parser.add_argument("--pdf", action="store_true", default=None, help="Generate publication-ready PDF report (auto-detected if browser is available)")
    parser.add_argument("--no-pdf", action="store_true", help="Do not generate PDF report")
    parser.add_argument("--html", action="store_true", default=True, help="Generate styled, interactive HTML report (default: enabled)")
    parser.add_argument("--no-html", action="store_true", help="Do not generate HTML report")
    parser.add_argument("--doc", "--txt", dest="doc", action="store_true", default=True, help="Generate plain-text test / executive document (.txt) (default: enabled)")
    parser.add_argument("--no-doc", "--no-txt", dest="no_doc", action="store_true", help="Do not generate plain-text document")
    parser.add_argument("--json", action="store_true", help="Also export report as JSON data")
    parser.add_argument("--all-formats", action="store_true", help="Generate all formats: Markdown, HTML, PDF, Text doc, and JSON")
    parser.add_argument("--stats", action="store_true", help="Fetch detailed additions/deletions/files stats for each commit")
    parser.add_argument("-r", "--repo", dest="repos", action="append", help="Filter specific repository name(s) (can be used multiple times)")
    parser.add_argument("--exclude", dest="exclude_repos", action="append", help="Exclude specific repository name(s)")
    parser.add_argument("--visibility", choices=["all", "public", "private"], default="all", help="Repository visibility (default: all)")
    parser.add_argument("--order", choices=["asc", "desc"], default="asc", help="Chronological sorting order for days (default: asc)")
    parser.add_argument("--no-markdown", action="store_true", help="Do not save Markdown file (terminal output only)")

    return parser


def main():
    parser = build_cli_parser()
    args = parser.parse_args()

    # Determine local git username/email as default identity fallback
    git_name, git_email = get_local_git_config()
    fallback_username = args.author or git_name

    # Resolve Dates
    start_input = args.start_date
    end_input = args.end_date

    # If neither start nor end is given on CLI and running interactively, prompt user
    stdin_is_atty = bool(sys.stdin and getattr(sys.stdin, "isatty", lambda: False)())
    if not start_input and not end_input and stdin_is_atty:
        start_input, end_input = prompt_for_dates()
    elif not start_input:
        start_input = "7d"
    if not end_input:
        end_input = "today"

    try:
        start_dt, end_dt = resolve_date_range(start_input, end_input)
    except ValueError as err:
        print(colorize(f"\n❌ Date Error: {err}\n", Style.RED + Style.BOLD))
        sys.exit(1)

    # -----------------------------------------------------------------------
    # Mode A: Local Directory Git Scan
    # -----------------------------------------------------------------------
    if args.local_dir:
        user_identity = args.author or fallback_username or "Developer"
        collector = LocalGitCollector(
            root_path=args.local_dir,
            start_dt=start_dt,
            end_dt=end_dt,
            specific_repos=args.repos,
            exclude_repos=args.exclude_repos,
            include_stats=args.stats,
            all_authors=args.all_authors,
            skip_merges=args.skip_merges,
            target_author=args.author
        )
    # -----------------------------------------------------------------------
    # Mode B: GitHub API Remote Scan
    # -----------------------------------------------------------------------
    else:
        # Resolve Token
        token = args.token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

        # In interactive terminal without token, prompt user
        if not token and stdin_is_atty and not args.author:
            token = prompt_for_token()

        if not token:
            print(colorize("\nℹ️  Notice: Running without a GitHub Token.", Style.YELLOW + Style.BOLD))
            print("  - Fetching public repositories for user: " + colorize(str(fallback_username), Style.BOLD))
            print("  - To include PRIVATE repositories and avoid rate limits, set GITHUB_TOKEN in .env or pass --token.\n")

        client = GitHubClient(token=token)

        # Resolve username for display
        user_identity = fallback_username or "Developer"
        if token:
            try:
                profile = client.get_authenticated_user()
                user_identity = profile.get("login") or profile.get("name") or user_identity
            except Exception:
                pass
        if args.author:
            user_identity = args.author

        collector = WorkCollector(
            client=client,
            start_dt=start_dt,
            end_dt=end_dt,
            fallback_username=fallback_username,
            specific_repos=args.repos,
            exclude_repos=args.exclude_repos,
            include_stats=args.stats,
            all_authors=args.all_authors,
            skip_merges=args.skip_merges,
            target_author=args.author,
            visibility=args.visibility
        )

    try:
        commits = collector.collect()
    except Exception as err:
        print(colorize(f"\n❌ Error collecting commits: {err}\n", Style.RED + Style.BOLD))
        sys.exit(1)

    # Generate Reports
    reverse_order = (args.order == "desc")
    reporter = ReportGenerator(commits, start_dt, end_dt, user_identity=user_identity)

    # 1. Rich Terminal report (Includes Executive Summary, Categorized What Changed, QA Checklist, and Timeline)
    reporter.print_terminal_report(reverse=reverse_order)

    # Base filename and path
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")
    base_name = f"github_work_report_{start_str}_to_{end_str}"
    reports_dir = "reports"
    os.makedirs(reports_dir, exist_ok=True)

    if args.output_file:
        base_target = args.output_file.rsplit(".", 1)[0]
    else:
        base_target = os.path.join(reports_dir, base_name)

    print(colorize("📁 GENERATED REPORTS:", Style.CYAN + Style.BOLD))

    # 2. Markdown Report (.md)
    if not args.no_markdown:
        md_path = base_target + ".md"
        saved_md = reporter.save_markdown(md_path, reverse=reverse_order)
        print(colorize(f"   📝 Markdown Report:  {saved_md}", Style.GREEN + Style.BOLD))

    # 3. Interactive & Styled HTML Report (.html)
    should_gen_html = not args.no_html or args.all_formats or (not args.no_pdf)
    if should_gen_html:
        html_path = base_target + ".html"
        saved_html = reporter.save_html(html_path, reverse=reverse_order)
        print(colorize(f"   🌐 Styled HTML Doc:  {saved_html}", Style.CYAN + Style.BOLD))

    # 4. Publication-Ready PDF Report (.pdf)
    should_gen_pdf = (args.pdf is True) or args.all_formats or (args.pdf is not False and not args.no_pdf)
    if should_gen_pdf:
        pdf_path = base_target + ".pdf"
        saved_pdf = reporter.save_pdf(pdf_path, reverse=reverse_order)
        if saved_pdf:
            print(colorize(f"   📄 Publication PDF:  {saved_pdf}", Style.YELLOW + Style.BOLD))
        else:
            browser = find_browser_for_pdf()
            if not browser:
                print(colorize("   ℹ️  PDF Auto-Export: No Chrome/Edge browser found. Open the HTML report and click 'Print / Save as PDF'.", Style.GRAY))

    # 5. Clean Plain-Text / Test Document (.txt)
    should_gen_doc = (not args.no_doc) or args.doc or args.all_formats
    if should_gen_doc:
        txt_path = base_target + ".txt"
        saved_txt = reporter.save_text_doc(txt_path, reverse=reverse_order)
        print(colorize(f"   📋 Plain Text Doc:   {saved_txt}", Style.WHITE + Style.BOLD))

    # 6. JSON Export (.json)
    if args.json or args.all_formats:
        json_path = base_target + ".json"
        saved_json = reporter.save_json(json_path)
        print(colorize(f"   💾 JSON Raw Data:    {saved_json}", Style.MAGENTA + Style.BOLD))

    print()


if __name__ == "__main__":
    main()

