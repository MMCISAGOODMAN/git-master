"""Integrate, backup, restore, and conflict preview services."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from git_service import (
    GitError,
    checkout_branch,
    create_backup_branch,
    get_current_branch,
    get_repo_path,
    is_working_tree_clean,
    restore_backup,
    run_git,
    sort_hashes_oldest_first,
    validate_branch_name,
    validate_hash,
)


EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class IntegrateJob:
    id: str
    status: str = "pending"  # pending|running|paused|completed|failed|aborted
    events: queue.Queue = field(default_factory=queue.Queue)
    report: dict[str, Any] = field(default_factory=dict)
    abort_requested: bool = False
    thread: threading.Thread | None = None


_jobs: dict[str, IntegrateJob] = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> IntegrateJob | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def _emit(job: IntegrateJob, event: dict[str, Any]) -> None:
    event.setdefault("ts", time.time())
    job.events.put(event)


def preview_conflicts(target: str, hashes: list[str]) -> dict[str, Any]:
    """Detect likely conflicts without modifying the working tree using merge-tree."""
    target = validate_branch_name(target)
    ordered = sort_hashes_oldest_first(hashes)
    conflicts: list[dict[str, Any]] = []

    for commit_hash in ordered:
        # merge-tree: merge commit into target tip without checkout
        # git merge-tree $(git merge-base target commit) target commit
        base = run_git(["merge-base", target, commit_hash])
        if base.returncode != 0:
            conflicts.append(
                {
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "reason": "Cannot find merge base",
                    "detail": base.stderr.strip(),
                }
            )
            continue
        base_hash = base.stdout.strip()
        tree = run_git(["merge-tree", base_hash, target, commit_hash])
        output = tree.stdout or ""
        # Conflict markers in merge-tree output
        if "changed in both" in output.lower() or "CONFLICT" in output:
            msg = run_git(["show", "-s", "--pretty=format:%s", commit_hash])
            conflicts.append(
                {
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "message": msg.stdout.strip() if msg.returncode == 0 else "",
                    "reason": "Potential content conflict",
                }
            )
        elif tree.returncode != 0:
            conflicts.append(
                {
                    "hash": commit_hash,
                    "short_hash": commit_hash[:7],
                    "reason": "merge-tree failed",
                    "detail": (tree.stderr or tree.stdout or "").strip(),
                }
            )

    return {
        "total": len(ordered),
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def _handle_conflict(job: IntegrateJob, strategy: str, commit_hash: str) -> str:
    """
    Handle cherry-pick conflict.
    Returns: 'resolved' | 'skipped' | 'paused' | 'failed'
    """
    if strategy == "skip":
        skip = run_git(["cherry-pick", "--skip"])
        if skip.returncode != 0:
            # try abort then continue without this commit
            run_git(["cherry-pick", "--abort"])
            _emit(
                job,
                {
                    "type": "log",
                    "level": "warn",
                    "message": f"Skipped conflicting commit {commit_hash[:7]} (abort fallback)",
                },
            )
            return "skipped"
        _emit(
            job,
            {
                "type": "log",
                "level": "warn",
                "message": f"Skipped conflicting commit {commit_hash[:7]}",
            },
        )
        return "skipped"

    if strategy == "ours":
        run_git(["checkout", "--ours", "."])
        run_git(["add", "-A"])
        cont = run_git(["cherry-pick", "--continue"], input_text="\n")
        if cont.returncode != 0:
            # empty commit after ours resolution
            empty = run_git(["-c", "core.editor=true", "cherry-pick", "--continue"])
            if empty.returncode != 0:
                run_git(["cherry-pick", "--abort"])
                _emit(
                    job,
                    {
                        "type": "log",
                        "level": "error",
                        "message": f"Failed to auto-resolve with --ours for {commit_hash[:7]}: "
                        f"{(empty.stderr or cont.stderr or '').strip()}",
                    },
                )
                return "failed"
        _emit(
            job,
            {
                "type": "log",
                "level": "warn",
                "message": f"Auto-resolved conflict with --ours for {commit_hash[:7]}",
            },
        )
        return "resolved"

    # pause
    job.status = "paused"
    _emit(
        job,
        {
            "type": "conflict",
            "hash": commit_hash,
            "short_hash": commit_hash[:7],
            "message": (
                f"Conflict on {commit_hash[:7]}. Resolve manually in the repo, then "
                "run `git cherry-pick --continue` or abort. Use Restore to roll back."
            ),
        },
    )
    _emit(
        job,
        {
            "type": "log",
            "level": "error",
            "message": f"Paused due to conflict on {commit_hash[:7]}",
        },
    )
    return "paused"


def _clear_cherry_pick_state(no_commit: bool) -> None:
    """Abort an in-progress cherry-pick without destroying prior squash staging."""
    if no_commit:
        # -n conflicts leave the index/worktree dirty; abort then keep staged squash changes
        run_git(["cherry-pick", "--abort"])
        return
    run_git(["cherry-pick", "--abort"])


def _cherry_pick_one(job: IntegrateJob, commit_hash: str, strategy: str, no_commit: bool) -> str:
    """
    Returns: success|skipped|paused|failed
    """
    args = ["cherry-pick"]
    if no_commit:
        args.append("-n")
    args.append(commit_hash)
    result = run_git(args)
    if result.returncode == 0:
        return "success"

    detail = (result.stderr or result.stdout or "").strip()
    detail_lower = detail.lower()
    # empty cherry-pick
    if (
        "previous cherry-pick is now empty" in detail_lower
        or "nothing to commit" in detail_lower
        or "the previous cherry-pick is now empty" in detail_lower
    ):
        if no_commit:
            # Nothing applied for this commit; ensure no leftover conflict state
            run_git(["cherry-pick", "--abort"])
        else:
            skip = run_git(["cherry-pick", "--skip"])
            if skip.returncode != 0:
                run_git(["cherry-pick", "--abort"])
        _emit(
            job,
            {
                "type": "log",
                "level": "warn",
                "message": f"Empty cherry-pick skipped for {commit_hash[:7]}",
            },
        )
        return "skipped"

    _emit(
        job,
        {
            "type": "log",
            "level": "warn",
            "message": f"Conflict or error on {commit_hash[:7]}: {detail[:300]}",
        },
    )
    if no_commit:
        # Conflict during squash accumulate: resolve or skip then continue accumulating
        if strategy == "skip":
            _clear_cherry_pick_state(True)
            # restore any unmerged paths to HEAD for this failed apply only —
            # staged changes from prior -n picks remain if abort preserves them.
            # cherry-pick --abort restores pre-pick state, undoing this pick only.
            _emit(
                job,
                {
                    "type": "log",
                    "level": "warn",
                    "message": f"Skipped conflicting commit {commit_hash[:7]} (squash)",
                },
            )
            return "skipped"
        if strategy == "ours":
            run_git(["checkout", "--ours", "."])
            run_git(["add", "-A"])
            # with -n there is no --continue; conflict resolved in index is enough
            _emit(
                job,
                {
                    "type": "log",
                    "level": "warn",
                    "message": f"Auto-resolved (--ours) for {commit_hash[:7]} (squash)",
                },
            )
            return "resolved"
        job.status = "paused"
        _emit(
            job,
            {
                "type": "conflict",
                "hash": commit_hash,
                "short_hash": commit_hash[:7],
                "message": (
                    f"Conflict on {commit_hash[:7]} during squash. "
                    "Resolve files, git add, then continue manually or restore backup."
                ),
            },
        )
        return "paused"

    return _handle_conflict(job, strategy, commit_hash)


def _run_integrate(
    job: IntegrateJob,
    *,
    source: str,
    target: str,
    hashes: list[str],
    mode: str,
    conflict_strategy: str,
    squash_message: str,
) -> None:
    success = 0
    skipped = 0
    conflicts = 0
    backup_name = ""
    original_branch = ""

    try:
        get_repo_path()
        source = validate_branch_name(source)
        target = validate_branch_name(target)
        ordered = sort_hashes_oldest_first(hashes)
        if not ordered:
            raise GitError("No valid commits selected")

        if not is_working_tree_clean():
            raise GitError("Working tree is not clean. Commit or stash changes before integrate.")

        original_branch = get_current_branch()
        job.status = "running"
        total = len(ordered)

        _emit(job, {"type": "log", "level": "info", "message": f"Creating backup of {target}..."})
        backup_name = create_backup_branch(target)
        _emit(
            job,
            {
                "type": "backup",
                "backup_branch": backup_name,
                "restore_command": f"git checkout {target} && git reset --hard {backup_name}",
            },
        )
        _emit(
            job,
            {
                "type": "log",
                "level": "info",
                "message": f"Backup branch created: {backup_name}",
            },
        )

        checkout_branch(target)
        _emit(job, {"type": "log", "level": "info", "message": f"Checked out target branch: {target}"})

        if mode == "squash":
            _emit(
                job,
                {
                    "type": "log",
                    "level": "info",
                    "message": f"Squash mode: applying {total} commits without committing...",
                },
            )
            for i, commit_hash in enumerate(ordered, start=1):
                if job.abort_requested:
                    job.status = "aborted"
                    _emit(job, {"type": "log", "level": "warn", "message": "Aborted by user"})
                    break

                _emit(
                    job,
                    {
                        "type": "progress",
                        "current": i,
                        "total": total,
                        "percent": int(i / total * 100),
                        "hash": commit_hash,
                    },
                )
                _emit(
                    job,
                    {
                        "type": "log",
                        "level": "info",
                        "message": f"[{i}/{total}] Applying {commit_hash[:7]} (no-commit)...",
                    },
                )
                outcome = _cherry_pick_one(job, commit_hash, conflict_strategy, no_commit=True)
                if outcome in ("success", "resolved"):
                    success += 1
                elif outcome == "skipped":
                    skipped += 1
                    conflicts += 1
                elif outcome == "paused":
                    conflicts += 1
                    break
                else:
                    conflicts += 1
                    job.status = "failed"
                    break
            else:
                # all applied — create single commit if there are staged changes
                status = run_git(["status", "--porcelain"])
                if status.stdout.strip():
                    msg = squash_message.strip() or f"chore: squash {success} commits from {source}"
                    commit = run_git(["commit", "-m", msg])
                    if commit.returncode != 0:
                        raise GitError("Failed to create squash commit", commit.stderr.strip())
                    _emit(
                        job,
                        {
                            "type": "log",
                            "level": "info",
                            "message": f"Created squash commit: {msg}",
                        },
                    )
                else:
                    _emit(
                        job,
                        {
                            "type": "log",
                            "level": "warn",
                            "message": "No changes to commit after squash apply",
                        },
                    )
                if job.status == "running":
                    job.status = "completed"
        else:
            # normal cherry-pick one by one
            for i, commit_hash in enumerate(ordered, start=1):
                if job.abort_requested:
                    job.status = "aborted"
                    _emit(job, {"type": "log", "level": "warn", "message": "Aborted by user"})
                    break

                _emit(
                    job,
                    {
                        "type": "progress",
                        "current": i,
                        "total": total,
                        "percent": int(i / total * 100),
                        "hash": commit_hash,
                    },
                )
                _emit(
                    job,
                    {
                        "type": "log",
                        "level": "info",
                        "message": f"[{i}/{total}] Cherry-picking {commit_hash[:7]}...",
                    },
                )
                outcome = _cherry_pick_one(job, commit_hash, conflict_strategy, no_commit=False)
                if outcome in ("success", "resolved"):
                    success += 1
                    _emit(
                        job,
                        {
                            "type": "log",
                            "level": "info",
                            "message": f"OK {commit_hash[:7]}",
                        },
                    )
                elif outcome == "skipped":
                    skipped += 1
                    conflicts += 1
                elif outcome == "paused":
                    conflicts += 1
                    break
                else:
                    conflicts += 1
                    job.status = "failed"
                    break
            else:
                if job.status == "running":
                    job.status = "completed"

        report = {
            "status": job.status,
            "success": success,
            "skipped": skipped,
            "conflicts": conflicts,
            "total": total,
            "backup_branch": backup_name,
            "restore_command": (
                f"git checkout {target} && git reset --hard {backup_name}" if backup_name else ""
            ),
            "target": target,
            "source": source,
            "mode": mode,
        }
        job.report = report
        _emit(job, {"type": "report", **report})
        if job.status == "completed":
            _emit(
                job,
                {
                    "type": "log",
                    "level": "info",
                    "message": (
                        f"Done. success={success}, skipped={skipped}, conflicts={conflicts}. "
                        f"Backup: {backup_name}"
                    ),
                },
            )
        _emit(job, {"type": "done", "status": job.status})

    except GitError as exc:
        job.status = "failed"
        _emit(job, {"type": "log", "level": "error", "message": exc.message})
        if exc.detail:
            _emit(job, {"type": "log", "level": "error", "message": exc.detail})
        job.report = {
            "status": "failed",
            "success": success,
            "skipped": skipped,
            "conflicts": conflicts,
            "backup_branch": backup_name,
            "error": exc.message,
            "detail": exc.detail,
        }
        _emit(job, {"type": "report", **job.report})
        _emit(job, {"type": "done", "status": "failed"})
        # try return to original branch if clean
        try:
            if original_branch and is_working_tree_clean():
                checkout_branch(original_branch)
        except Exception:
            pass
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        _emit(job, {"type": "log", "level": "error", "message": str(exc)})
        job.report = {"status": "failed", "error": str(exc), "backup_branch": backup_name}
        _emit(job, {"type": "report", **job.report})
        _emit(job, {"type": "done", "status": "failed"})


def start_integrate(
    *,
    source: str,
    target: str,
    hashes: list[str],
    mode: str = "normal",
    conflict_strategy: str = "pause",
    squash_message: str = "",
) -> IntegrateJob:
    if mode not in ("normal", "squash"):
        raise GitError("Invalid integrate mode", mode)
    if conflict_strategy not in ("pause", "skip", "ours"):
        raise GitError("Invalid conflict strategy", conflict_strategy)
    if not hashes:
        raise GitError("No commits selected")

    job = IntegrateJob(id=uuid.uuid4().hex)
    with _jobs_lock:
        _jobs[job.id] = job

    thread = threading.Thread(
        target=_run_integrate,
        kwargs={
            "job": job,
            "source": source,
            "target": target,
            "hashes": hashes,
            "mode": mode,
            "conflict_strategy": conflict_strategy,
            "squash_message": squash_message,
        },
        daemon=True,
    )
    job.thread = thread
    thread.start()
    return job


def abort_job(job_id: str) -> IntegrateJob:
    job = get_job(job_id)
    if not job:
        raise GitError("Job not found", job_id)
    job.abort_requested = True
    # if paused in cherry-pick, abort the pick
    run_git(["cherry-pick", "--abort"])
    job.status = "aborted"
    _emit(job, {"type": "log", "level": "warn", "message": "Abort requested"})
    _emit(job, {"type": "done", "status": "aborted"})
    return job


def do_restore(backup_branch: str, target_branch: str) -> None:
    restore_backup(backup_branch, target_branch)
