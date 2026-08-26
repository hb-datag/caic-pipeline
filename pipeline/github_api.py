"""Minimal GitHub API client — reads files and makes atomic multi-file commits.

Why the low-level Git Data API: one meeting run touches many files (ledger,
summary page, index, concept pages). Committing them all in ONE commit keeps
the repo history clean — one commit per run — which is the concept ledger's
audit trail.

Auth: fine-grained token (Contents: read/write) from the `caic-github`
Modal secret (GITHUB_TOKEN + GITHUB_REPO, e.g. "user/caic-pipeline").
"""

import base64
import os

import requests


class GitHubRepo:
    def __init__(self, token: str | None = None, repo: str | None = None,
                 branch: str = "main"):
        self.token = token or os.environ["GITHUB_TOKEN"]
        self.repo = repo or os.environ["GITHUB_REPO"]
        self.branch = branch
        self.api = f"https://api.github.com/repos/{self.repo}"
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _get(self, url: str) -> dict:
        r = self.s.get(url, timeout=60)
        r.raise_for_status()
        return r.json()

    def _post(self, url: str, payload: dict) -> dict:
        r = self.s.post(url, json=payload, timeout=120)
        r.raise_for_status()
        return r.json()

    def get_file(self, path: str) -> str | None:
        """Return the decoded text content of a repo file, or None if absent."""
        r = self.s.get(f"{self.api}/contents/{path}", params={"ref": self.branch},
                       timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def commit_files(self, files: dict[str, str], message: str) -> str:
        """Commit {path: text_content} atomically. Returns the new commit sha."""
        head = self._get(f"{self.api}/git/ref/heads/{self.branch}")
        head_sha = head["object"]["sha"]
        base_tree = self._get(f"{self.api}/git/commits/{head_sha}")["tree"]["sha"]

        tree = [{"path": p, "mode": "100644", "type": "blob", "content": c}
                for p, c in files.items()]
        new_tree = self._post(f"{self.api}/git/trees",
                              {"base_tree": base_tree, "tree": tree})
        commit = self._post(f"{self.api}/git/commits", {
            "message": message, "tree": new_tree["sha"], "parents": [head_sha]})
        r = self.s.patch(f"{self.api}/git/refs/heads/{self.branch}",
                         json={"sha": commit["sha"]}, timeout=60)
        r.raise_for_status()
        return commit["sha"]

    @property
    def pages_base_url(self) -> str:
        from . import config
        if config.PAGES_URL:
            return config.PAGES_URL.rstrip("/")
        owner, name = self.repo.split("/", 1)
        return f"https://{owner}.github.io/{name}"
