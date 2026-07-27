"""Git command wrappers and validation for the commit integrator."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

BRANCH_PATTERN = re.compile(r"^[\w./\-]+$")
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")
COMMIT_TYPE_PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?!?:\s*",
    re.IGNORECASE,
)
KNOWN_TYPES = ("feat", "fix", "docs", "style", "refactor", "test", "chore")


class GitError(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class RepoState:
    path: str | None = None


repo_state = RepoState()


def validate_branch_name(name: str) -> str:
    if not name or not BRANCH_PATTERN.match(name):
        raise GitError("Invalid branch name", name or "")
    if ".." in name:
        raise GitError("Invalid branch name", name)
    return name


def validate_hash(value: str) -> str:
    if not value or not HASH_PATTERN.match(value):
        raise GitError("Invalid commit hash", value or "")
    return value


def set_repo_path(path: str) -> str:
    if not path or not path.strip():
        raise GitError("Repository path is required")
    resolved = os.path.realpath(os.path.expanduser(path.strip()))
    if not os.path.isdir(resolved):
        raise GitError("Path does not exist or is not a directory", resolved)
    git_dir = os.path.join(resolved, ".git")
    if not (os.path.isdir(git_dir) or os.path.isfile(git_dir)):
        raise GitError("Path is not a Git repository", resolved)
    repo_state.path = resolved
    return resolved


def get_repo_path() -> str:
    if not repo_state.path:
        raise GitError("No repository configured. Set a path first.")
    return repo_state.path


def run_git(
    args: list[str],
    *,
    cwd: str | None = None,
    check: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    repo = cwd or get_repo_path()
    cmd = ["git", *args]
    result = subprocess.run(
        cmd,
        cwd=repo,
        capture_output=True,
        text=True,
        input=input_text,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GitError(f"Git command failed: git {' '.join(args)}", detail)
    return result


def detect_commit_type(message: str) -> str:
    match = COMMIT_TYPE_PATTERN.match(message or "")
    if match:
        return match.group(1).lower()
    return "other"


def get_repo_info() -> dict[str, Any]:
    path = get_repo_path()
    branch = get_current_branch()
    clean = is_working_tree_clean()
    return {
        "path": path,
        "current_branch": branch,
        "clean": clean,
    }


def get_current_branch() -> str:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if result.returncode != 0:
        raise GitError("Failed to get current branch", result.stderr.strip())
    return result.stdout.strip()


def is_working_tree_clean() -> bool:
    result = run_git(["status", "--porcelain"])
    return result.returncode == 0 and not result.stdout.strip()


def list_branches() -> dict[str, Any]:
    result = run_git(["branch", "--format=%(refname:short)"])
    if result.returncode != 0:
        raise GitError("Failed to list branches", result.stderr.strip())
    branches = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    current = get_current_branch()
    return {"branches": branches, "current": current}


def list_authors(source: str) -> list[dict[str, Any]]:
    source = validate_branch_name(source)
    result = run_git(["log", source, "--pretty=format:%an"])
    if result.returncode != 0:
        raise GitError("Failed to list authors", result.stderr.strip())
    counts: dict[str, int] = {}
    for name in result.stdout.splitlines():
        name = name.strip()
        if not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    authors = [{"name": name, "count": count} for name, count in counts.items()]
    authors.sort(key=lambda item: (-item["count"], item["name"].lower()))
    return authors


def _parse_log_line(line: str) -> dict[str, Any] | None:
    # hash|author|iso_date|subject
    parts = line.split("|", 3)
    if len(parts) < 4:
        return None
    full_hash, author, date_raw, message = parts
    short_hash = full_hash[:7]
    commit_type = detect_commit_type(message)
    try:
        dt = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        date_display = dt.strftime("%Y-%m-%d %H:%M:%S")
        date_sort = dt.timestamp()
    except ValueError:
        date_display = date_raw
        date_sort = 0.0
    return {
        "hash": full_hash,
        "short_hash": short_hash,
        "author": author,
        "date": date_display,
        "date_raw": date_raw,
        "date_sort": date_sort,
        "message": message,
        "message_short": message[:50] + ("…" if len(message) > 50 else ""),
        "type": commit_type,
    }


def list_commits(
    source: str,
    *,
    authors: list[str] | None = None,
    types: list[str] | None = None,
    keyword: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_by: str = "date",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    source = validate_branch_name(source)
    args = [
        "log",
        source,
        "--pretty=format:%H|%an|%aI|%s",
    ]
    if date_from:
        args.append(f"--since={date_from} 00:00:00")
    if date_to:
        args.append(f"--until={date_to} 23:59:59")

    result = run_git(args)
    if result.returncode != 0:
        raise GitError("Failed to list commits", result.stderr.strip())

    commits: list[dict[str, Any]] = []
    author_set = set(authors or [])
    type_set = {t.lower() for t in (types or [])}
    keyword_lower = (keyword or "").strip().lower()

    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        item = _parse_log_line(line)
        if not item:
            continue
        if author_set and item["author"] not in author_set:
            continue
        if type_set and item["type"] not in type_set:
            continue
        if keyword_lower and keyword_lower not in item["message"].lower():
            continue
        commits.append(item)

    reverse = sort_order.lower() != "asc"
    if sort_by == "author":
        commits.sort(key=lambda c: c["author"].lower(), reverse=reverse)
    elif sort_by == "message":
        commits.sort(key=lambda c: c["message"].lower(), reverse=reverse)
    else:
        commits.sort(key=lambda c: c["date_sort"], reverse=reverse)

    total = len(commits)
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size
    page_items = commits[start:end]
    for idx, item in enumerate(page_items, start=start + 1):
        item["index"] = idx

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": page_items,
    }


def get_commit_detail(commit_hash: str) -> dict[str, Any]:
    commit_hash = validate_hash(commit_hash)
    meta = run_git(
        ["show", "-s", "--pretty=format:%H|%an|%ae|%aI|%B", commit_hash],
        check=True,
    )
    raw = meta.stdout
    # %B may contain newlines; first line has meta separators for first 4 fields
    first_sep = raw.find("|")
    second_sep = raw.find("|", first_sep + 1)
    third_sep = raw.find("|", second_sep + 1)
    fourth_sep = raw.find("|", third_sep + 1)
    if fourth_sep < 0:
        raise GitError("Failed to parse commit detail", raw)
    full_hash = raw[:first_sep]
    author = raw[first_sep + 1 : second_sep]
    email = raw[second_sep + 1 : third_sep]
    date_raw = raw[third_sep + 1 : fourth_sep]
    message = raw[fourth_sep + 1 :].rstrip("\n")

    stat = run_git(["show", "--stat", "--format=", commit_hash])
    numstat = run_git(["show", "--numstat", "--format=", commit_hash])
    additions = 0
    deletions = 0
    for line in numstat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            try:
                if parts[0] != "-":
                    additions += int(parts[0])
                if parts[1] != "-":
                    deletions += int(parts[1])
            except ValueError:
                continue

    return {
        "hash": full_hash,
        "short_hash": full_hash[:7],
        "author": author,
        "email": email,
        "date": date_raw,
        "message": message,
        "type": detect_commit_type(message.split("\n", 1)[0]),
        "stat": stat.stdout.strip(),
        "additions": additions,
        "deletions": deletions,
    }


def get_stats_for_hashes(hashes: list[str]) -> dict[str, Any]:
    if not hashes:
        return {
            "selected_count": 0,
            "author_count": 0,
            "additions": 0,
            "deletions": 0,
            "authors": [],
        }
    validated = [validate_hash(h) for h in hashes]
    authors: set[str] = set()
    additions = 0
    deletions = 0
    for h in validated:
        meta = run_git(["show", "-s", "--pretty=format:%an", h])
        if meta.returncode == 0 and meta.stdout.strip():
            authors.add(meta.stdout.strip())
        numstat = run_git(["show", "--numstat", "--format=", h])
        for line in numstat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    if parts[0] != "-":
                        additions += int(parts[0])
                    if parts[1] != "-":
                        deletions += int(parts[1])
                except ValueError:
                    continue
    return {
        "selected_count": len(validated),
        "author_count": len(authors),
        "additions": additions,
        "deletions": deletions,
        "authors": sorted(authors),
    }


def checkout_branch(branch: str) -> None:
    branch = validate_branch_name(branch)
    result = run_git(["checkout", branch])
    if result.returncode != 0:
        raise GitError(f"Failed to checkout branch {branch}", result.stderr.strip())


def create_backup_branch(target: str) -> str:
    target = validate_branch_name(target)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # sanitize target for branch name (slashes -> dashes)
    safe_target = target.replace("/", "-")
    backup_name = f"backup-{safe_target}-{stamp}"
    validate_branch_name(backup_name)
    # create backup from target tip without switching away first
    result = run_git(["branch", backup_name, target])
    if result.returncode != 0:
        raise GitError("Failed to create backup branch", result.stderr.strip())
    return backup_name


def restore_backup(backup_branch: str, target_branch: str) -> None:
    backup_branch = validate_branch_name(backup_branch)
    target_branch = validate_branch_name(target_branch)
    if not is_working_tree_clean():
        raise GitError("Working tree is not clean. Commit or stash changes before restore.")
    checkout_branch(target_branch)
    result = run_git(["reset", "--hard", backup_branch])
    if result.returncode != 0:
        raise GitError("Failed to restore from backup", result.stderr.strip())


def sort_hashes_oldest_first(hashes: list[str]) -> list[str]:
    validated = [validate_hash(h) for h in hashes]
    if not validated:
        return []
    # git rev-list --no-walk --reverse orders by commit time ascending
    result = run_git(["rev-list", "--no-walk", "--reverse", *validated])
    if result.returncode != 0:
        raise GitError("Failed to order commits", result.stderr.strip())
    ordered = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    # keep only requested hashes (rev-list may expand if invalid)
    requested = set(validated)
    # map short to full if needed
    full_map: dict[str, str] = {}
    for h in validated:
        show = run_git(["rev-parse", h], check=True)
        full_map[h] = show.stdout.strip()
        requested.add(show.stdout.strip())
    return [h for h in ordered if h in requested]
