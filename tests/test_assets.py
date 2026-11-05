"""Exercise public asset restoration, corruption rejection and safe extraction."""
import contextlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tarfile
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from portfolio.assets import AssetError, Distribution, digest, download, extract_images, fingerprint


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.files = self.root / "files"
        self.files.mkdir()
        self.source = self.root / "source"
        self.source.mkdir()
        image = self.source / "slide.webp"
        image.write_bytes(b"a complete image payload")
        self.item = {"path": "decks/example/0001.webp", "sha256": digest(image), "bytes": image.stat().st_size}
        self.archive = self.source / "images.tar"
        with tarfile.open(self.archive, "w") as archive:
            archive.add(image, arcname=self.item["path"])
        class Handler(SimpleHTTPRequestHandler):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, directory=str(self.source), **kwargs)
            def log_message(*args):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.record = {"name": "images.tar", "url": f"http://127.0.0.1:{self.server.server_port}/images.tar",
                       "bytes": self.archive.stat().st_size, "sha256": digest(self.archive)}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.work.cleanup()

    def test_complete_download_and_file_verification(self):
        target = self.root / "download.tar"
        download(self.record, target)
        extract_images(target, self.files, [self.item])
        self.assertEqual(digest(self.files / self.item["path"]), self.item["sha256"])

    def test_corrupt_download_leaves_existing_file_intact(self):
        target = self.root / "download.tar"
        target.write_bytes(b"existing")
        with self.assertRaisesRegex(AssetError, "checksum"):
            download({**self.record, "sha256": "0" * 64}, target)
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertFalse(target.with_suffix(".tar.part").exists())

    def test_truncated_response_is_rejected(self):
        with self.assertRaisesRegex(AssetError, "checksum"):
            download({**self.record, "bytes": self.record["bytes"] + 1}, self.root / "download.tar")

    def test_undeclared_and_traversal_entries_are_rejected(self):
        with tarfile.open(self.archive, "w") as archive:
            info = tarfile.TarInfo("../escape")
            info.size = 4
            archive.addfile(info, io.BytesIO(b"test"))
        with self.assertRaises(AssetError):
            extract_images(self.archive, self.files, [self.item])
        self.assertFalse((self.root / "escape").exists())

    def test_symlinks_are_rejected(self):
        with tarfile.open(self.archive, "w") as archive:
            info = tarfile.TarInfo(self.item["path"])
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            archive.addfile(info)
        with self.assertRaisesRegex(AssetError, "Unsafe"):
            extract_images(self.archive, self.files, [self.item])

    def test_fresh_cache_fetch_and_draft_scope(self):
        bundle = {"id": "example", "files": [self.item]}
        catalog = {"version": 1, "repository": "phrawzty/assets.dark.ca", "release": "portfolio-assets-v1",
                   "bundles": {"example": {"fingerprint": fingerprint(bundle), "images": self.record}}}
        (self.root / "data").mkdir()
        (self.root / "data/asset-releases.json").write_text(json.dumps(catalog))
        scopes = []
        project = SimpleNamespace(root=self.root, asset_dir=self.files, settings={},
                                  bundles=lambda include_drafts: scopes.append(include_drafts) or [bundle])
        with contextlib.redirect_stdout(io.StringIO()):
            Distribution(project).fetch(production=True)
        self.assertEqual(scopes, [False])
        self.assertEqual(digest(self.files / self.item["path"]), self.item["sha256"])
        # A verified cache works with no network or release available.
        self.archive.unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            Distribution(project).fetch()

    def test_unpublished_bundle_has_actionable_error(self):
        project = SimpleNamespace(root=self.root, settings={})
        with self.assertRaisesRegex(AssetError, "portfolio assets publish"):
            Distribution(project).record({"id": "new", "files": [self.item]})

    def test_release_inventory_includes_every_api_page(self):
        distribution = Distribution(SimpleNamespace(root=self.root, settings={}))
        distribution.gh = Mock(side_effect=[{"id": 123}, [[{"name": "first"}], [{"name": "last"}]]])
        self.assertEqual(set(distribution.release_assets()), {"first", "last"})
        self.assertIn("--paginate", distribution.gh.call_args.args)
