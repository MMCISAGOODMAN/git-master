"""Flask entry for Git Commit Integrator."""

from __future__ import annotations

import argparse
import json
import os
import queue
from typing import Any

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from git_service import (
    GitError,
    get_commit_detail,
    get_repo_info,
    get_stats_for_hashes,
    list_authors,
    list_branches,
    list_commits,
    repo_state,
    set_repo_path,
)
from integrate_service import (
    abort_job,
    do_restore,
    get_job,
    preview_conflicts,
    start_integrate,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
CORS(app)


def ok(data: Any = None, **extra: Any) -> Response:
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload)


def fail(message: str, detail: str = "", status: int = 400) -> tuple[Response, int]:
    return jsonify({"ok": False, "error": message, "detail": detail}), status


@app.errorhandler(GitError)
def handle_git_error(exc: GitError):
    return fail(exc.message, exc.detail, 400)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/repo")
def api_get_repo():
    if not repo_state.path:
        return ok({"path": None, "current_branch": None, "clean": True, "configured": False})
    info = get_repo_info()
    info["configured"] = True
    return ok(info)


@app.post("/api/repo")
def api_set_repo():
    body = request.get_json(silent=True) or {}
    path = body.get("path") or ""
    resolved = set_repo_path(path)
    info = get_repo_info()
    info["configured"] = True
    info["path"] = resolved
    return ok(info)


@app.get("/api/branches")
def api_branches():
    return ok(list_branches())


@app.get("/api/authors")
def api_authors():
    source = request.args.get("source") or ""
    if not source:
        return fail("source branch is required")
    return ok(list_authors(source))


@app.get("/api/commits")
def api_commits():
    source = request.args.get("source") or ""
    if not source:
        return fail("source branch is required")

    authors = request.args.getlist("author")
    if not authors and request.args.get("authors"):
        authors = [a for a in request.args.get("authors", "").split(",") if a]

    types = request.args.getlist("type")
    if not types and request.args.get("types"):
        types = [t for t in request.args.get("types", "").split(",") if t]

    try:
        page = int(request.args.get("page", 1))
        page_size = int(request.args.get("page_size", 20))
    except ValueError:
        return fail("Invalid page or page_size")

    result = list_commits(
        source,
        authors=authors or None,
        types=types or None,
        keyword=request.args.get("keyword") or "",
        date_from=request.args.get("date_from") or "",
        date_to=request.args.get("date_to") or "",
        sort_by=request.args.get("sort_by") or "date",
        sort_order=request.args.get("sort_order") or "desc",
        page=page,
        page_size=page_size,
    )
    return ok(result)


@app.get("/api/commits/<commit_hash>")
def api_commit_detail(commit_hash: str):
    return ok(get_commit_detail(commit_hash))


@app.get("/api/stats")
def api_stats():
    hashes = request.args.getlist("hash")
    if not hashes and request.args.get("hashes"):
        hashes = [h for h in request.args.get("hashes", "").split(",") if h]
    total = 0
    if repo_state.path and request.args.get("source"):
        # optional total commits for source without filters
        from git_service import list_commits as lc

        total_data = lc(request.args.get("source") or "", page=1, page_size=1)
        total = total_data["total"]
    stats = get_stats_for_hashes(hashes)
    stats["total_commits"] = total
    return ok(stats)


@app.post("/api/integrate/preview")
def api_integrate_preview():
    body = request.get_json(silent=True) or {}
    target = body.get("target") or ""
    hashes = body.get("hashes") or []
    if not target:
        return fail("target is required")
    if not hashes:
        return fail("hashes are required")
    return ok(preview_conflicts(target, hashes))


@app.post("/api/integrate")
def api_integrate():
    body = request.get_json(silent=True) or {}
    source = body.get("source") or ""
    target = body.get("target") or ""
    hashes = body.get("hashes") or []
    mode = body.get("mode") or "normal"
    conflict_strategy = body.get("conflict_strategy") or "pause"
    squash_message = body.get("squash_message") or ""
    if not source or not target:
        return fail("source and target are required")
    job = start_integrate(
        source=source,
        target=target,
        hashes=hashes,
        mode=mode,
        conflict_strategy=conflict_strategy,
        squash_message=squash_message,
    )
    return ok({"job_id": job.id})


@app.get("/api/integrate/<job_id>/stream")
def api_integrate_stream(job_id: str):
    job = get_job(job_id)
    if not job:
        return fail("Job not found", job_id, 404)

    def generate():
        yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id})}\n\n"
        while True:
            try:
                event = job.events.get(timeout=1.0)
            except queue.Empty:
                if job.status in ("completed", "failed", "aborted") and job.events.empty():
                    break
                yield ": keepalive\n\n"
                continue
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") == "done":
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/integrate/<job_id>/abort")
def api_integrate_abort(job_id: str):
    job = abort_job(job_id)
    return ok({"job_id": job.id, "status": job.status})


@app.post("/api/backup/restore")
def api_backup_restore():
    body = request.get_json(silent=True) or {}
    backup_branch = body.get("backup_branch") or ""
    target_branch = body.get("target_branch") or ""
    if not backup_branch or not target_branch:
        return fail("backup_branch and target_branch are required")
    do_restore(backup_branch, target_branch)
    return ok({"restored": True, "backup_branch": backup_branch, "target_branch": target_branch})


def parse_args():
    parser = argparse.ArgumentParser(description="Git Commit Integrator Web UI")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GIT_REPO_PATH", ""),
        help="Default local Git repository path (or set GIT_REPO_PATH)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    # Avoid 5000: macOS AirPlay Receiver (AirTunes) often binds it and returns 403.
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.port == 5000:
        print(
            "Warning: port 5000 is commonly used by macOS AirPlay Receiver "
            "and may return HTTP 403. Prefer --port 5001 (default)."
        )
    if args.repo:
        try:
            set_repo_path(args.repo)
            print(f"Repository: {repo_state.path}")
        except GitError as exc:
            print(f"Warning: could not set repo ({exc.message}): {exc.detail}")
    else:
        print("No default repo. Configure path in the web UI or pass --repo.")

    print(f"Open http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
