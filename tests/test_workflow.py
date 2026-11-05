"""Exercise the real authoring workflow, version isolation, and offline production builds."""
import contextlib
from datetime import date
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from portfolio.cli import Portfolio, PortfolioError, UserCancelled, main, read_page, write_page, sha256
from portfolio.assets import fingerprint

SOURCE = Path(__file__).resolve().parents[1]


def scaffold(root):
    for name in ("content", "templates", "themes", "static", "data"):
        shutil.copytree(SOURCE / name, root / name)
    for name in ("zola.toml", "portfolio.toml"):
        shutil.copy2(SOURCE / name, root / name)
    config = root / "portfolio.toml"
    config.write_text(config.read_text().replace('../assets.dark.ca/files', 'assets'))
    # Authoring tests must also work on a fresh checkout with no asset cache.
    (root / "data/site-assets.json").unlink(missing_ok=True)
    (root / "content/bio.md").write_text('+++\ntitle = "About"\n+++\n\nWorkflow test fixture.\n')
    # Tests never import or alter real portfolio entries.
    for directory in (root / "content/appearances", root / "content/talks"):
        for path in directory.glob("*.md"):
            if path.name != "_index.md":
                path.unlink()
    (root / ".portfolio").mkdir(exist_ok=True)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.seed = Path(cls.fixture.name)
        scaffold(cls.seed)
        project = Portfolio(cls.seed)
        cls.call_at(cls.seed, "new", "--id", "seed", "--title", "Workflow example", "--event", "Example event",
                    "--date", "2020-01-01", "--location", "Paris, France", "--timezone", "Europe/Paris")
        cls.v1 = project.attach_pdf("seed", SOURCE / "tests/fixtures/deck-v1.pdf")
        cls.v2 = project.attach_pdf("seed", SOURCE / "tests/fixtures/deck-v2.pdf")
        catalog = {"version": 1, "repository": "phrawzty/assets.dark.ca", "release": "portfolio-assets-v1", "bundles": {}}
        for version in (cls.v1, cls.v2):
            deck = project.deck(version)
            item = next(item for item in deck["files"] if item["path"] == deck["pdf"])
            catalog["bundles"][version] = {"fingerprint": fingerprint(deck), "pdf": {**item,
                "url": f"https://github.com/phrawzty/assets.dark.ca/releases/download/portfolio-assets-v1/{version}.pdf"}}
        (cls.seed / "data/asset-releases.json").write_text(json.dumps(catalog))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    @staticmethod
    def call_at(root, *arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["--root", str(root), *arguments])
        if result:
            raise AssertionError(f"Command failed: {arguments}")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        scaffold(self.root)
        shutil.copytree(self.seed / "assets", self.root / "assets", dirs_exist_ok=True)
        shutil.copytree(self.seed / "data/decks", self.root / "data/decks", dirs_exist_ok=True)
        shutil.copy2(self.seed / "data/asset-releases.json", self.root / "data/asset-releases.json")
        self.project = Portfolio(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, *arguments):
        self.call_at(self.root, *arguments)

    def create(self, ident="first", publish=False):
        self.call("new", "--id", ident, "--title", "A living portfolio", "--event", "Example event",
                  "--date", "2030-05-01", "--location", "Paris, France", "--timezone", "Europe/Paris",
                  *(["--publish"] if publish else []))

    def test_three_everyday_cases_and_deck_isolation(self):
        # Upcoming announcement without slides.
        self.create(publish=True)
        self.project.build()
        self.assertIn("A living portfolio", (self.root / "public/index.html").read_text())
        self.assertTrue((self.root / "public/first/index.html").exists())
        # First event gets slides; explicit reuse selects that version for a repeat.
        self.call("slides", "first", str(SOURCE / "tests/fixtures/deck-v1.pdf"))
        self.call("new", "--from", "first", "--reuse-slides", "--id", "repeat", "--event", "A different event", "--date", "2030-06-01",
                  "--location", "Paris, France", "--timezone", "Europe/Paris", "--publish")
        self.assertEqual(read_page(self.root / "content/appearances/repeat.md")[0]["extra"]["deck"], self.v1)
        original_bytes = (self.root / "assets" / self.project.deck(self.v1)["pdf"]).read_bytes()
        self.call("slides", "repeat", str(SOURCE / "tests/fixtures/deck-v2.pdf"))
        self.assertEqual(read_page(self.root / "content/appearances/first.md")[0]["extra"]["deck"], self.v1)
        self.assertEqual(read_page(self.root / "content/appearances/repeat.md")[0]["extra"]["deck"], self.v2)
        self.assertEqual(original_bytes, (self.root / "assets" / self.project.deck(self.v1)["pdf"]).read_bytes())
        # Recording and feedback are event-specific.
        self.call("recording", "first", "https://www.youtube.com/watch?v=0s8ATQmhQPE")
        self.assertEqual(read_page(self.root / "content/appearances/repeat.md")[0]["extra"]["recording_url"], "")
        self.project.build()
        self.assertIn("Watch the recording", (self.root / "public/first/index.html").read_text())
        self.assertNotIn("Watch the recording", (self.root / "public/repeat/index.html").read_text())
        self.assertTrue((self.root / "public/first/slides/index.html").exists())
        self.assertIn("Slide 3", (self.root / "public/repeat/slides/index.html").read_text())
        self.assertNotIn("/first/slides/slide-1", (self.root / "public/_redirects").read_text())

    def test_drafts_stay_out_of_pages_lists_and_feed(self):
        self.create()
        self.project.build()
        self.assertFalse((self.root / "public/first").exists())
        self.assertNotIn("A living portfolio", (self.root / "public/index.html").read_text())
        self.assertNotIn("A living portfolio", (self.root / "public/talks/index.html").read_text())
        self.call("publish", "first")
        self.project.build()
        self.assertTrue((self.root / "public/first/index.html").exists())

    def test_same_pdf_reuses_processing(self):
        self.create()
        with patch("portfolio.cli.run", side_effect=AssertionError("No renderer should run for cached deck")):
            self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")

    def test_modified_immutable_assets_fail_checks(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        deck = self.project.deck(self.v1)
        (self.root / "assets" / deck["slides"][0]["image"]).write_bytes(b"changed")
        with self.assertRaisesRegex(PortfolioError, "Immutable asset was modified"):
            self.project.check()

    def test_comments_and_markdown_survive_recording_update(self):
        self.create()
        path = self.root / "content/appearances/first.md"
        path.write_text(path.read_text().replace('[extra]', '# Keep this explanation\n[extra]') + "\nA **hand-edited** description.\n")
        self.call("recording", "first", "https://example.com/recording")
        self.assertIn("# Keep this explanation", path.read_text())
        self.assertIn("A **hand-edited** description.", path.read_text())

    def test_resource_link_and_transcript_validation(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        path = self.root / "data/decks" / (self.v1 + ".json")
        deck = json.loads(path.read_text())
        deck["slides"][0]["text"] = '<script>alert("example")</script>'
        path.write_text(json.dumps(deck))
        self.project.build()
        rendered = (self.root / "public/first/slides/index.html").read_text()
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn('<script>alert("example")</script>', rendered)

    def test_production_build_requires_available_local_assets(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        deck = self.project.deck(self.v1)
        (self.root / "assets" / deck["pdf"]).unlink()
        # A production build uses the verified release PDF; local previews need its bytes.
        self.project.build()
        self.assertIn("https://github.com/phrawzty/assets.dark.ca/releases/download/", (self.root / "public/first/index.html").read_text())
        self.assertFalse(list((self.root / "public/assets").rglob("*.pdf")))
        with self.assertRaisesRegex(PortfolioError, "Missing local asset"):
            self.project.build(local=True)

    def test_production_image_size_limit(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        with patch("portfolio.cli.PAGE_LIMIT", 1), self.assertRaisesRegex(PortfolioError, "25 MiB image limit"):
            self.project.check(production=True)

    def test_removed_asset_upload_command_is_not_available(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--root", str(self.root), "assets", "sync"])
        self.assertEqual(error.exception.code, 2)

    def test_editable_notes_do_not_change_source_deck_or_assets(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        original = self.root / "data/decks" / (self.v1 + ".json")
        before = original.read_bytes()
        self.call("notes", "first")
        notes = self.root / "notes" / (self.v1 + ".toml")
        notes.write_text(notes.read_text().replace('title = ""', 'title = "A corrected title"', 1))
        self.project.build()
        self.assertEqual(before, original.read_bytes())
        self.assertIn("A corrected title", (self.root / "public/first/slides/index.html").read_text())

    def test_broken_internal_resource_prevents_publication_build(self):
        self.create(publish=True)
        path = self.root / "content/appearances/first.md"
        meta, body = read_page(path)
        meta["extra"]["resources"] = [{"title": "Missing", "url": "/does-not-exist/"}]
        write_page(path, meta, body)
        with self.assertRaisesRegex(PortfolioError, "Broken internal links"):
            self.project.build()

    def test_chooser_searches_by_event_without_needing_an_id(self):
        self.create("first")
        self.create("second")
        path = self.root / "content/appearances/second.md"
        meta, body = read_page(path)
        meta["extra"]["event"] = "A specific conference"
        write_page(path, meta, body)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["specific", "1"]):
            self.assertEqual(self.project.choose_appearance(), "second")

    def test_add_slides_with_only_interactive_prompts(self):
        self.create()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["1", '"' + str(SOURCE / "tests/fixtures/deck-v1.pdf") + '"']):
            self.call("slides")
        self.assertEqual(read_page(self.root / "content/appearances/first.md")[0]["extra"]["deck"], self.v1)

    def test_markdown_path_works_for_noninteractive_commands(self):
        self.create()
        self.call("slides", "content/appearances/first.md", str(SOURCE / "tests/fixtures/deck-v1.pdf"))
        self.assertEqual(read_page(self.root / "content/appearances/first.md")[0]["extra"]["deck"], self.v1)

    def test_menu_creates_a_draft_and_opens_its_markdown(self):
        answers = ["1", "A new talk", "Another event", "2031-02-03", "Paris, France", "", "", "q"]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=answers), patch.object(Portfolio, "open_editor") as editor:
            self.call()
        path = self.root / "content/appearances/2031-02-03-another-event.md"
        meta, body = read_page(path)
        self.assertTrue(meta["draft"])
        self.assertEqual(meta["title"], "A new talk")
        editor.assert_called_once_with(path.resolve())

    def test_repeat_enter_leaves_slides_empty_and_previous_event_unchanged(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        self.project.recording("first", "https://example.com/recording")
        previous = (self.root / "content/appearances/first.md").read_bytes()
        answers = ["1", "", "Another event", "2031-02-03", "Paris, France", "", ""]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=answers), patch.object(Portfolio, "open_editor"):
            self.call("repeat")
        meta, _ = read_page(self.root / "content/appearances/2031-02-03-another-event.md")
        self.assertEqual(meta["extra"]["deck"], "")
        self.assertEqual(meta["extra"]["recording_url"], "")
        self.assertEqual((self.root / "content/appearances/first.md").read_bytes(), previous)

    def test_repeat_can_explicitly_reuse_previous_slides(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        answers = ["1", "", "Another event", "2031-02-03", "Paris, France", "", "reuse"]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=answers), patch.object(Portfolio, "open_editor"):
            self.call("repeat")
        meta, _ = read_page(self.root / "content/appearances/2031-02-03-another-event.md")
        self.assertEqual(meta["extra"]["deck"], self.v1)

    def test_scripted_repeat_also_starts_without_slides(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        self.call("new", "--from", "first", "--event", "Another event", "--date", "2031-02-03", "--location", "Paris, France", "--timezone", "Europe/Paris")
        meta, _ = read_page(self.root / "content/appearances/2031-02-03-another-event.md")
        self.assertEqual(meta["extra"]["deck"], "")

    def test_cancel_chooser_does_not_modify_content(self):
        self.create()
        path = self.root / "content/appearances/first.md"
        before = path.read_bytes()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            self.call("recording")
        self.assertEqual(path.read_bytes(), before)

    def test_url_alone_uses_the_recording_chooser(self):
        self.create()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["1"]):
            self.call("recording", "https://example.com/recording")
        meta, _ = read_page(self.root / "content/appearances/first.md")
        self.assertEqual(meta["extra"]["recording_url"], "https://example.com/recording")

    def test_publication_menu_lists_only_drafts(self):
        self.create("published", publish=True)
        self.create("draft")
        path = self.root / "content/appearances/published.md"
        meta, body = read_page(path)
        meta["title"] = "Already published talk"
        write_page(path, meta, body)
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["8", "1", "q"]), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root)]), 0)
        self.assertIn("Choose a draft", output.getvalue())
        self.assertNotIn("Already published talk", output.getvalue())
        self.assertFalse(read_page(self.root / "content/appearances/draft.md")[0]["draft"])

    def test_publication_with_no_drafts_returns_without_asking_for_a_selection(self):
        self.create(publish=True)
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=AssertionError("There is nothing to choose")), contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root), "publish"]), 0)
        self.assertIn("No drafts waiting for publication", output.getvalue())

    def test_check_report_explains_success_scope_and_draft_counts(self):
        self.create("draft")
        self.create("published", publish=True)
        self.project.attach_pdf("draft", SOURCE / "tests/fixtures/deck-v1.pdf")
        before = (self.root / "content/appearances/draft.md").read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root), "check"]), 0)
        report = output.getvalue()
        self.assertIn("PASS — portfolio consistency checks completed", report)
        self.assertIn("2 appearances: 1 draft, 1 included in production builds", report)
        self.assertIn("sizes and checksums", report)
        self.assertIn("external URL availability", report)
        self.assertIn("No files were changed or uploaded", report)
        self.assertEqual((self.root / "content/appearances/draft.md").read_bytes(), before)

    def test_failed_check_names_the_talk_and_problem_without_claiming_success(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        deck = self.project.deck(self.v1)
        (self.root / "assets" / deck["slides"][0]["image"]).unlink()
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(main(["--root", str(self.root), "check"]), 1)
        self.assertIn("FAIL", output.getvalue())
        self.assertNotIn("PASS —", output.getvalue())
        self.assertIn("A living portfolio", errors.getvalue())
        self.assertIn("Missing local asset", errors.getvalue())
        self.assertIn("Fix this item", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
