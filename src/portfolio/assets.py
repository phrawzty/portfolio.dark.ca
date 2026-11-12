"""Plain Git asset checkouts, pinned builds and portable PDF URLs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote


class AssetError(ValueError):
    pass


class AssetRepository:
    def __init__(self, project):
        self.project = project
        self.checkout = project.asset_dir.parent
        self.settings = project.settings.get("assets", {})
        self.lock_path = project.root / "data/assets-lock.json"
        self._trees = {}

    def git(self, *args, cwd=None, input=None):
        result = subprocess.run(["git", *args], cwd=cwd or self.checkout,
                                input=input, capture_output=True)
        if result.returncode:
            raise AssetError(result.stderr.decode().strip() or "Git command failed")
        return result.stdout

    def revision(self):
        if not self.lock_path.exists():
            raise AssetError("Assets are not recorded for deployment. Run 'portfolio assets publish' first.")
        revision = json.loads(self.lock_path.read_text())["revision"]
        if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision):
            raise AssetError("Invalid assets commit in data/assets-lock.json")
        return revision

    def tree(self):
        revision = self.revision()
        if revision not in self._trees:
            if not (self.checkout / ".git").exists():
                raise AssetError("Missing assets Git checkout. Run 'portfolio assets fetch'.")
            result = self.git("ls-tree", "-rz", revision, "--", "files/")
            records = {}
            for record in result.split(b"\0"):
                if record:
                    info, path = record.split(b"\t", 1)
                    mode, kind, checksum = info.split()
                    if kind == b"blob" and mode in (b"100644", b"100755"):
                        records[path.decode()] = checksum.decode()
            self._trees[revision] = records
        return self._trees[revision]

    def verify_committed(self, bundle):
        tree = self.tree()
        for item in bundle["files"]:
            path = self.project.asset_dir / item["path"]
            key = "files/" + item["path"]
            expected = tree.get(key)
            if expected:
                checksum = hashlib.new("sha1" if len(expected) == 40 else "sha256")
                checksum.update(f"blob {path.stat().st_size}\0".encode())
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        checksum.update(block)
                if checksum.hexdigest() == expected:
                    continue
            raise AssetError(f"{key} is not in the recorded assets commit. Run 'portfolio publish' to prepare and push the release.")

    def required_paths(self):
        return {"files/" + item["path"] for bundle in self.project.bundles(include_drafts=False)
                for item in bundle["files"]}

    def pending_paths(self):
        """Return production assets whose local bytes are absent from the lock."""
        tree = self.tree()
        pending = set()
        for relative in self.required_paths():
            path = self.checkout / relative
            expected = tree.get(relative)
            if not expected or not path.is_file():
                pending.add(relative)
                continue
            checksum = hashlib.new("sha1" if len(expected) == 40 else "sha256")
            checksum.update(f"blob {path.stat().st_size}\0".encode())
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(block)
            if checksum.hexdigest() != expected:
                pending.add(relative)
        return pending

    def pdf_url(self, path):
        base = self.settings.get("public_base_url", "")
        if not base:
            raise AssetError("Set assets.public_base_url to the HTTP location serving the assets files")
        return base.format(revision=self.revision()).rstrip("/") + "/" + quote(path, safe="/")

    def fetch(self):
        """CI clones the pinned revision; existing author checkouts are never reset."""
        revision = self.revision()
        if not self.checkout.exists():
            self.checkout.parent.mkdir(parents=True, exist_ok=True)
            self.git("clone", "--no-checkout", "--depth=1", self.settings["repository"], str(self.checkout), cwd=self.checkout.parent)
            try:
                self.git("cat-file", "-e", revision + "^{commit}")
            except AssetError:
                self.git("fetch", "--depth=1", "origin", revision)
            self.git("checkout", "--detach", revision)
        else:
            head = self.git("rev-parse", "HEAD").decode().strip()
            if head != revision:
                raise AssetError(f"Assets checkout is at {head[:12]}, but this portfolio requires {revision[:12]}. Fetch the required commit and switch to it, or publish your newer assets. Local changes were not touched.")
        for bundle in self.project.bundles(include_drafts=False):
            self.project.verify_assets(bundle, production=True)
        print("Assets checkout verified at " + revision[:12] + ". PDFs and images are ordinary Git files.")

    def prepare(self):
        """Commit pending public assets locally and pin the resulting revision."""
        if not (self.checkout / ".git").exists():
            raise AssetError("Clone the assets repository alongside this portfolio first")
        bundles = self.project.bundles(include_drafts=False)
        paths = self.required_paths()
        for bundle in bundles:
            self.project.verify_assets(bundle)
        staged = set(self.git("diff", "--cached", "--name-only", "-z").decode().strip("\0").split("\0")) - {""}
        if staged - paths:
            raise AssetError("The assets repo has other staged changes. Commit or unstage those first; nothing was added or pushed.")
        pending = self.pending_paths()
        if pending:
            self.git("add", "--pathspec-from-file=-", "--pathspec-file-nul",
                     input=b"\0".join(path.encode() for path in sorted(pending)) + b"\0")
        if self.git("diff", "--cached", "--name-only"):
            self.git("commit", "-m", "Update public presentation assets", "-m", "Prepared by portfolio publish.")
        elif pending:
            raise AssetError("Referenced assets differ from the lock but produced no Git changes")
        else:
            return None
        revision = self.git("rev-parse", "HEAD").decode().strip()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.lock_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"revision": revision}, indent=2) + "\n")
        temporary.replace(self.lock_path)
        self._trees.clear()
        for bundle in bundles:
            self.verify_committed(bundle)
        print("Prepared assets commit " + revision[:12] + ".")
        return revision

    def push(self):
        self.git("push")

    def publish(self):
        """Recovery command: prepare and immediately push referenced assets."""
        revision = self.prepare()
        if revision is None:
            print("Referenced assets already match data/assets-lock.json; nothing to push.")
            return None
        self.push()
        print("Assets pushed at " + revision[:12] + ". Commit data/assets-lock.json with your portfolio changes.")
        return revision
