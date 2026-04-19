from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel
from temporalio import activity

from aiop.settings import get_settings
from aiop.types import GitCommitResult


class GitCommitInput(BaseModel):
    req_id: str
    repo_url: str
    branch: str = "main"
    files: list[tuple[str, str]]
    commit_message: str


def _auth_url(url: str, token: str) -> str:
    if not token or not url.startswith("http"):
        return url
    parsed = urlparse(url)
    netloc = f"x-access-token:{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


async def _run(*args: str, cwd: str | None = None, env: dict | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


@activity.defn(name="git_commit")
async def git_commit(payload: GitCommitInput) -> GitCommitResult:
    s = get_settings()
    workdir = s.workdir_for(payload.req_id, "git")
    repo_dir = workdir / "repo"
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    auth_url = _auth_url(payload.repo_url, s.github_token)

    rc, out, err = await _run("git", "clone", "--depth", "1", "--branch", payload.branch, auth_url, str(repo_dir))
    if rc != 0:
        raise RuntimeError(f"git clone failed: {err}")

    activity.heartbeat({"req_id": payload.req_id, "stage": "writing_files"})

    written_paths: list[str] = []
    for rel_path, content in payload.files:
        target = repo_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        written_paths.append(rel_path)

    env = {
        "GIT_AUTHOR_NAME": s.git_author_name,
        "GIT_AUTHOR_EMAIL": s.git_author_email,
        "GIT_COMMITTER_NAME": s.git_author_name,
        "GIT_COMMITTER_EMAIL": s.git_author_email,
        "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin",
    }

    await _run("git", "add", *written_paths, cwd=str(repo_dir), env=env)
    rc, out, err = await _run("git", "commit", "-m", payload.commit_message, cwd=str(repo_dir), env=env)
    if rc != 0:
        if "nothing to commit" in (out + err):
            raise RuntimeError("No changes to commit (PRD identical to existing).")
        raise RuntimeError(f"git commit failed: {err}")

    activity.heartbeat({"req_id": payload.req_id, "stage": "pushing"})
    rc, out, err = await _run("git", "push", "origin", payload.branch, cwd=str(repo_dir), env=env)
    if rc != 0:
        raise RuntimeError(f"git push failed: {err}")

    rc, sha_out, _ = await _run("git", "rev-parse", "HEAD", cwd=str(repo_dir), env=env)
    sha = sha_out.strip()

    parsed = urlparse(payload.repo_url)
    commit_url = None
    if "github.com" in (parsed.hostname or ""):
        path = parsed.path.rstrip(".git").rstrip("/")
        commit_url = f"https://github.com{path}/commit/{sha}"

    return GitCommitResult(
        repo=payload.repo_url,
        branch=payload.branch,
        commit_sha=sha,
        files_changed=written_paths,
        commit_url=commit_url,
    )
