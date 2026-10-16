# 📊 GitHub Day-Wise Work & Progress Reporter (GUI & CLI)

A complete solution to fetch commit changes across **public and private** GitHub repositories and generate human-readable work reports, change logs, and QA test documents.

Available both as a **standalone Windows Desktop GUI Application (`.exe`)** and a **command-line CLI tool**.

---

## 🖥️ Standalone Windows Desktop App (`.exe`)

You can share the compiled single executable with any Windows user:

- **Location:** [`dist/GitHubWorkReporter.exe`](dist/GitHubWorkReporter.exe)
- **Zero Requirements:** End-users do **NOT** need Python, Git, or pip installed.
- **Double-Click & Run:** No installation wizard required.

### 🌟 Desktop App Features:

1. **🔐 GitHub Connection Tab:** Enter your Personal Access Token, test connection, view token scopes, remaining API limits, and user profile card.
2. **📊 Reporting Tab:** Date range picker with quick presets (_Today, Yesterday, Last 7 Days, This Week, Last 14 Days, Last 30 Days, This Month_), repository filters, and one-click buttons to open **PDF**, **HTML Dashboard**, **Plain Text Doc**, and **Markdown**.
3. **🔄 Version & Auto-Update Tab:** Shows current version (`v1.1.0`), queries the public GitHub repository releases, displays new release notes, and downloads & self-updates the executable automatically!

To rebuild the executable at any time:

```bash
python build_exe.py
```

---

## 🚀 Features

- **Human-Readable Executive Reporting:** Automatically transforms raw git commits into clean business actions organized into functional domains (Security & Access Control, External Integrations, UI/UX Dashboards, APIs & Backend, Features, Bug Fixes).
- **QA & Test Verification Checklist:** Automatically generates an actionable test & QA verification checklist ("What to Test") from the code updates.
- **Multi-Format Export (Zero extra dependencies):**
  - 📄 **Publication-Ready PDF:** Native headless browser export (using Microsoft Edge or Chrome built into your system).
  - 🌐 **Interactive Styled HTML:** Executive dashboard layout with KPI badges, category filtering, and print stylesheet (`@media print` with 1-click Print / Save as PDF button).
  - 📋 **Plain-Text / Test Doc (.txt):** Clean, border-formatted document ready for email updates, Slack, Jira, or pasting into Microsoft Word.
  - 📝 **GitHub-Flavored Markdown (.md):** Structured report with direct commit links.
  - 💾 **JSON Data:** Complete structured output for external workflows.
- **Public & Private Repositories:** Full access across all your repos (including forks and collaborations) using a GitHub Personal Access Token (PAT).
- **Graceful Tokenless Mode:** Can still scan public repositories even if no token is provided.
- **Smart Author Matching:** Automatically links your GitHub username, git config email/name, and common variations so no commits are missed.
- **Day-Wise & Repo-Wise Organization:** Commits are grouped by work day in your local timezone and organized by repository.
- **Visual Terminal Output:** Colorized dashboard with summary metrics, category highlights, and activity bars.
- **Commit Stats:** Optional `--stats` flag to fetch line additions (+), deletions (-), and files changed for each commit.
- **Filter Merges:** Use `--skip-merges` to focus exclusively on your feature and fix commits.
- **Zero Required Pip Packages:** Runs with standard Python 3. Supports `python-dotenv` if installed.

---

## 🛠️ Setup & Authentication

To scan **private repositories** and avoid GitHub's unauthenticated rate limits (60/hr vs 5,000/hr):

1. Generate a Personal Access Token on GitHub:
   - Go to [GitHub Token Settings](https://github.com/settings/tokens).
   - Generate a **Classic Token** with the `repo` scope (or a **Fine-grained Token** with Read access to repository contents and metadata).
2. Create a `.env` file in this directory (or copy from `.env.example`):
   ```env
   GITHUB_TOKEN=ghp_yourPersonalAccessTokenHere
   ```
   _(Or you can simply enter your token when prompted interactively, and the script can save it for you)._

---

## 💻 Usage Examples

### 1. Interactive Mode

Simply run the script. It will guide you with helpful defaults and generate **Markdown, HTML, PDF, and Text Doc** reports:

```bash
python reportingscript.py
```

### 2. Specific Date Range

```bash
python reportingscript.py --start 2026-10-01 --end 2026-10-15
```

### 3. Quick Relative Keywords

```bash
# Past 7 days
python reportingscript.py --start 7d --end today

# This week's work
python reportingscript.py --start this-week

# Past 30 days / month
python reportingscript.py --start 30d
```

### 4. Generate All Formats (Markdown, HTML, PDF, Text Doc, JSON)

```bash
python reportingscript.py --start 14d --all-formats
```

### 5. Clean Feature Commits with Detailed Diff Stats (+ / - lines)

```bash
python reportingscript.py --start 7d --stats --skip-merges
```

### 6. Filter Specific Repositories

```bash
python reportingscript.py --start 7d --repo rdgboos --repo start_tag
```

---

## ⚙️ Command-Line Arguments Reference

| Argument                      | Description                                                                                    | Default                          |
| :---------------------------- | :--------------------------------------------------------------------------------------------- | :------------------------------- |
| `-s`, `--start`               | Start date (`YYYY-MM-DD`, `today`, `yesterday`, `7d`, `14d`, `30d`, `this-week`, `this-month`) | 7 days ago                       |
| `-e`, `--end`                 | End date (`YYYY-MM-DD`, `today`, etc.)                                                         | Today                            |
| `-t`, `--token`               | GitHub Personal Access Token                                                                   | `GITHUB_TOKEN` from `.env`       |
| `-a`, `--author`              | Target author username or email                                                                | Authenticated user / git config  |
| `--pdf` / `--no-pdf`          | Generate publication-ready PDF report (auto-detected if Edge/Chrome available)                 | `Auto`                           |
| `--html` / `--no-html`        | Generate styled, interactive HTML report with 1-click Print/PDF                                | `True`                           |
| `--doc`, `--txt` / `--no-doc` | Generate plain-text test / executive document (`.txt`)                                         | `True`                           |
| `--all-formats`               | Generate all formats (Markdown, HTML, PDF, Text doc, and JSON)                                 | `False`                          |
| `--skip-merges`               | Exclude branch merge commits from the report                                                   | `False`                          |
| `--stats`                     | Fetch lines added/deleted and files touched per commit                                         | `False`                          |
| `--json`                      | Also export the report as a `.json` file                                                       | `False`                          |
| `-r`, `--repo`                | Filter specific repo name (can be repeated)                                                    | All repos                        |
| `--exclude`                   | Exclude specific repo name (can be repeated)                                                   | None                             |
| `--visibility`                | Repo visibility filter: `all`, `public`, `private`                                             | `all`                            |
| `--order`                     | Sort days chronologically: `asc` or `desc`                                                     | `asc`                            |
| `-o`, `--output`              | Custom destination base path for reports                                                       | `reports/github_work_report_...` |
