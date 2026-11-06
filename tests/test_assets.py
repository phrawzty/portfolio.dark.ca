"""Verify ordinary Git publication, pinned checkouts and portable PDF hosting."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from portfolio.assets import AssetError, AssetRepository


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE).decode().strip()


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.source = self.root / "source"
        self.source.mkdir()
        git(self.source, "init", "-b", "main")
        git(self.source, "config", "user.name", "Asset test")
        git(self.source, "config", "user.email", "assets@example.invalid")
        (self.source / "files/decks/a-readable-talk").mkdir(parents=True)
        (self.source / "files/decks/a-readable-talk/a-readable-talk.pdf").write_bytes(b"preserved pdf bytes")
        git(self.source, "add", "files")
        git(self.source, "commit", "-m", "Original assets")
        self.revision = git(self.source, "rev-parse", "HEAD")
        self.site = self.root / "site"
        (self.site / "data").mkdir(parents=True)
        (self.site / "data/assets-lock.json").write_text(json.dumps({"revision": self.revision}))
        self.bundle = {"files": [{"path": "decks/a-readable-talk/a-readable-talk.pdf"}]}
        self.checked = []
        self.project = SimpleNamespace(root=self.site, asset_dir=self.root / "clone/files",
            settings={"assets": {"repository": str(self.source), "public_base_url": "https://mirror.example/{revision}/files"}},
            bundles=lambda include_drafts: [self.bundle],
            verify_assets=lambda bundle, **kwargs: self.checked.append((bundle, kwargs)))

    def tearDown(self):
        self.work.cleanup()

    def test_fresh_clone_contains_real_pdfs_without_releases_or_lfs(self):
        assets = AssetRepository(self.project)
        assets.fetch()
        path = self.project.asset_dir / "decks/a-readable-talk/a-readable-talk.pdf"
        self.assertEqual(path.read_bytes(), b"preserved pdf bytes")
        self.assertEqual(git(assets.checkout, "rev-parse", "HEAD"), self.revision)
        self.assertEqual(self.checked[0][1], {"production": True})
        assets.verify_committed(self.bundle)

    def test_changed_or_uncommitted_bytes_are_rejected(self):
        self.project.asset_dir = self.source / "files"
        assets = AssetRepository(self.project)
        (self.source / "files/decks/a-readable-talk/a-readable-talk.pdf").write_bytes(b"modified")
        with self.assertRaisesRegex(AssetError, "not in the recorded assets commit"):
            assets.verify_committed(self.bundle)

    def test_existing_checkout_is_never_reset_to_another_revision(self):
        self.project.asset_dir = self.source / "files"
        (self.source / "personal-notes.txt").write_text("keep my edits")
        git(self.source, "add", "personal-notes.txt")
        git(self.source, "commit", "-m", "Newer assets")
        head = git(self.source, "rev-parse", "HEAD")
        with self.assertRaisesRegex(AssetError, "Local changes were not touched"):
            AssetRepository(self.project).fetch()
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), head)
        self.assertEqual((self.source / "personal-notes.txt").read_text(), "keep my edits")

    def test_portable_pdf_base_url_and_readable_escaped_filename(self):
        url = AssetRepository(self.project).pdf_url("decks/a-readable-talk/a readable talk.pdf")
        self.assertEqual(url, f"https://mirror.example/{self.revision}/files/decks/a-readable-talk/a%20readable%20talk.pdf")

    def test_plain_git_publish_pushes_only_public_files_then_records_commit(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "clone", "--bare", str(self.source), str(remote)], check=True, capture_output=True)
        git(self.source, "remote", "add", "origin", str(remote))
        git(self.source, "push", "-u", "origin", "main")
        self.project.asset_dir = self.source / "files"
        (self.source / "files/decks/a-readable-talk/a-readable-talk.pdf").write_bytes(b"new public version")
        (self.source / "private-draft.txt").write_text("must remain untracked")
        assets = AssetRepository(self.project)
        assets.publish()
        revision = json.loads((self.site / "data/assets-lock.json").read_text())["revision"]
        self.assertNotEqual(revision, self.revision)
        self.assertEqual(git(remote, "rev-parse", "main"), revision)
        self.assertNotIn("private-draft.txt", git(self.source, "ls-tree", "-r", "--name-only", "HEAD"))
        assets.verify_committed(self.bundle)

    def test_publish_does_not_commit_unrelated_staged_changes(self):
        self.project.asset_dir = self.source / "files"
        (self.source / "notes.txt").write_text("not part of this upload")
        git(self.source, "add", "notes.txt")
        with self.assertRaisesRegex(AssetError, "other staged changes"):
            AssetRepository(self.project).publish()
        self.assertEqual(git(self.source, "rev-parse", "HEAD"), self.revision)
