"""Exercise the real authoring workflow, version isolation, and offline production builds."""
import contextlib
from datetime import date
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from portfolio.cli import Portfolio, PortfolioError, UserCancelled, main, read_page, write_page, sha256
import subprocess

SOURCE = Path(__file__).resolve().parents[1]


def scaffold(root):
    for name in ("content", "templates", "themes", "static", "data"):
        shutil.copytree(SOURCE / name, root / name)
    for name in ("zola.toml", "portfolio.toml"):
        shutil.copy2(SOURCE / name, root / name)
    config = root / "portfolio.toml"
    config.write_text(config.read_text().replace('../assets.dark.ca/files', 'assets-repo/files'))
    # Authoring tests must also work on a fresh checkout with no asset cache.
    (root / "data/site-assets.json").unlink(missing_ok=True)
    (root / "content/bio.md").write_text('+++\ntitle = "About"\n+++\n\nWorkflow test fixture.\n')
    # Tests never import or alter real portfolio entries.
    for directory in (root / "content/appearances", root / "content/talks"):
        for path in directory.glob("*.md"):
            if path.name != "_index.md":
                path.unlink()
    (root / ".portfolio").mkdir(exist_ok=True)
    # Test locations belong to the fixture, independently of the live registry.
    (root / "data/places.toml").write_text('[[place]]\nid = "paris-fr"\nname = "Paris, France"\nlat = 48.856614\nlng = 2.352222\n')


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
        checkout = project.asset_dir.parent
        for command in (["init", "-b", "main"], ["config", "user.name", "Workflow test"],
                        ["config", "user.email", "workflow@example.invalid"], ["add", "files"],
                        ["commit", "-qm", "Fixture assets"]):
            subprocess.run(["git", "-C", str(checkout), *command], check=True, capture_output=True)
        revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"]).decode().strip()
        (cls.seed / "data/assets-lock.json").write_text(json.dumps({"revision": revision}))

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
        shutil.copytree(self.seed / "assets-repo", self.root / "assets-repo", dirs_exist_ok=True)
        shutil.copytree(self.seed / "data/decks", self.root / "data/decks", dirs_exist_ok=True)
        shutil.copy2(self.seed / "data/assets-lock.json", self.root / "data/assets-lock.json")
        self.project = Portfolio(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def call(self, *arguments):
        self.call_at(self.root, *arguments)

    def create(self, ident="first", publish=False):
        self.call("new", "--id", ident, "--title", "A living portfolio", "--event", "Example event",
                  "--date", "2030-05-01", "--location", "Paris, France", "--timezone", "Europe/Paris",
                  *(["--publish"] if publish else []))

    def initialize_publish_repositories(self):
        remotes = self.root / ".test-remotes"
        remotes.mkdir()
        portfolio_remote = remotes / "portfolio.git"
        assets_remote = remotes / "assets.git"
        for remote in (portfolio_remote, assets_remote):
            remote.mkdir()
            subprocess.run(["git", "-C", str(remote), "init", "--bare", "-q"], check=True)

        subprocess.run(["git", "-C", str(self.root), "init", "-b", "main", "-q"], check=True)
        (self.root / ".git/info/exclude").write_text(".portfolio/\npublic/\nassets-repo/\n.test-remotes/\n")
        for key, value in (("user.name", "Portfolio test"), ("user.email", "portfolio@example.invalid")):
            subprocess.run(["git", "-C", str(self.root), "config", key, value], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "Portfolio baseline"], check=True)
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", str(portfolio_remote)], check=True)
        subprocess.run(["git", "-C", str(self.root), "push", "-qu", "origin", "main"], check=True)

        assets = self.project.asset_repository.checkout
        subprocess.run(["git", "-C", str(assets), "remote", "add", "origin", str(assets_remote)], check=True)
        subprocess.run(["git", "-C", str(assets), "push", "-qu", "origin", "main"], check=True)
        return portfolio_remote, assets_remote

    def test_new_appearance_does_not_prompt_for_timezone(self):
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=[
            "A living portfolio", "Example event", "2030-05-01", "Paris, France",
        ]) as prompt:
            self.call("new", "--id", "rio")
        self.assertEqual(prompt.call_count, 4)
        path = self.project.appearance("rio")[0]
        meta, _ = read_page(path)
        self.assertNotIn("timezone", meta["extra"])
        self.project.validate_page(path, meta)
        self.project.build()

    def test_place_references_and_labels_build_offline_without_source_duplication(self):
        self.create("first", publish=True)
        self.create("second", publish=True)
        path, meta, body = self.project.appearance("second")
        meta["extra"]["location_label"] = "Paris · Venue <A>"
        write_page(path, meta, body)
        self.project.locations.save("Paris, FR", 48.856614, 2.352222, "paris-fr")
        with patch("portfolio.locations.urlopen", side_effect=AssertionError("Build must remain offline")):
            self.project.build()
        points = json.loads((self.root / "public/appearances-map.json").read_text())["points"]
        self.assertEqual(len(points), 2)
        self.assertEqual({p["place"] for p in points}, {"paris-fr"})
        self.assertEqual({p["location"] for p in points}, {"Paris, FR"})
        self.assertIn("Paris, FR", (self.root / "public/first/index.html").read_text())
        self.assertIn("Paris · Venue &lt;A&gt;", (self.root / "public/second/index.html").read_text())
        source, _ = read_page(path)
        self.assertNotIn("resolved_location", source["extra"])

    def test_hand_edited_invalid_locations_fail_checks_and_builds(self):
        self.create(publish=True)
        path, original, body = self.project.appearance("first")
        for update in ({"place": "missing"}, {"place": ""}, {"latitude": 48}, {"location": "Paris"}, {"virtual": True}, {"virtual": "false"}, {"location_label": ""}):
            with self.subTest(update=update):
                meta, _ = read_page(path)
                for key in ("place", "latitude", "location", "virtual", "location_label"):
                    meta["extra"].pop(key, None)
                meta["extra"].update(place="paris-fr", virtual=False)
                meta["extra"].update(update)
                write_page(path, meta, body)
                with self.assertRaises(PortfolioError):
                    self.project.check()
                with self.assertRaises(PortfolioError):
                    self.project.build()
        write_page(path, original, body)

    def test_optional_timezone_is_preserved_and_validated(self):
        self.create()
        path = self.project.appearance("first")[0]
        meta, _ = read_page(path)
        self.assertEqual(meta["extra"]["timezone"], "Europe/Paris")
        self.project.validate_page(path, meta)
        for timezone in ("Unknown/Timezone", ""):
            with self.subTest(timezone=timezone):
                meta["extra"]["timezone"] = timezone
                with self.assertRaisesRegex(PortfolioError, "unknown timezone"):
                    self.project.validate_page(path, meta)
                with self.assertRaises(AssertionError):
                    self.call("new", "--id", "invalid", "--title", "Example", "--event", "Event",
                              "--date", "2030-05-01", "--location", "Virtual", "--timezone", timezone)
                self.assertFalse(any(m["extra"]["id"] == "invalid" for _, m, _ in self.project.appearances()))

    def test_readable_filenames_keep_stable_ids_urls_and_everyday_commands(self):
        self.create("Legacy42")
        path, meta, body = self.project.appearance("Legacy42")
        self.assertEqual(path.name, "2030-05-01-example-event.md")
        self.assertEqual(meta["path"], "Legacy42")
        meta["aliases"] = ["Legacy42/previous-title"]
        write_page(path, meta, body)
        renamed = path.with_name("2030-05-01-renamed-event.md")
        path.rename(renamed)
        self.assertEqual(self.project.appearance("Legacy42")[0], renamed)
        self.assertEqual(self.project.appearance(renamed.stem)[0], renamed)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="1"):
            self.assertEqual(self.project.choose_appearance(), "Legacy42")
        self.call("recording", str(renamed.relative_to(self.project.root)), "https://example.com/recording")
        self.call("slides", "Legacy42", str(SOURCE / "tests/fixtures/deck-v1.pdf"))
        self.project.mark_ready("Legacy42")
        self.project.build()
        public = self.root / "public"
        self.assertTrue((public / "Legacy42/index.html").exists())
        self.assertTrue((public / "Legacy42/slides/index.html").exists())
        self.assertFalse((public / renamed.stem).exists())
        self.assertIn("/Legacy42/previous-title /Legacy42/ 301", (public / "_redirects").read_text())
        meta, _ = read_page(renamed)
        self.assertEqual(meta["extra"]["id"], "Legacy42")
        self.assertEqual(meta["extra"]["recording_url"], "https://example.com/recording")

    def test_duplicate_id_is_rejected_even_after_renaming_its_file(self):
        self.create("Legacy42")
        path = self.project.appearance("Legacy42")[0]
        path.rename(path.with_name("2030-05-01-another-filename.md"))
        before = set((self.root / "content/appearances").glob("*.md"))
        with self.assertRaises(AssertionError):
            self.create("Legacy42")
        self.assertEqual(before, set((self.root / "content/appearances").glob("*.md")))

    def test_same_event_date_allocates_readable_filenames_without_overwriting(self):
        self.create("first")
        self.create("second")
        self.assertEqual(self.project.appearance("first")[0].name, "2030-05-01-example-event.md")
        self.assertEqual(self.project.appearance("second")[0].name, "2030-05-01-example-event-2.md")
        self.assertEqual(self.project.appearance("second")[1]["path"], "second")

    def test_id_lookup_rejects_duplicate_front_matter_ids(self):
        self.create("Legacy42")
        path = self.project.appearance("Legacy42")[0]
        path.with_name("2030-05-01-duplicate.md").write_bytes(path.read_bytes())
        with self.assertRaisesRegex(PortfolioError, "Ambiguous appearance"):
            self.project.appearance("Legacy42")

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
        self.assertEqual(read_page(self.project.appearance("repeat")[0])[0]["extra"]["deck"], self.v1)
        original_bytes = (self.project.asset_dir / self.project.deck(self.v1)["pdf"]).read_bytes()
        self.call("slides", "repeat", str(SOURCE / "tests/fixtures/deck-v2.pdf"))
        self.assertEqual(read_page(self.project.appearance("first")[0])[0]["extra"]["deck"], self.v1)
        self.assertEqual(read_page(self.project.appearance("repeat")[0])[0]["extra"]["deck"], self.v2)
        self.assertEqual(original_bytes, (self.project.asset_dir / self.project.deck(self.v1)["pdf"]).read_bytes())
        # Recording and feedback are event-specific.
        self.call("recording", "first", "https://www.youtube.com/watch?v=0s8ATQmhQPE")
        self.assertEqual(read_page(self.project.appearance("repeat")[0])[0]["extra"]["recording_url"], "")
        self.project.build()
        self.assertIn("Watch the recording", (self.root / "public/first/index.html").read_text())
        self.assertNotIn("Watch the recording", (self.root / "public/repeat/index.html").read_text())
        self.assertTrue((self.root / "public/first/slides/index.html").exists())
        self.assertFalse((self.root / "public/first/present").exists())
        viewer = (self.root / "public/first/index.html").read_text()
        self.assertIn("data-fullscreen", viewer)
        self.assertIn("All slides &amp; transcript", viewer)
        self.assertNotIn("Presentation view", viewer)
        self.assertNotIn("/first/present/", viewer)
        self.assertIn("Slide 3", (self.root / "public/repeat/slides/index.html").read_text())
        self.assertNotIn("/first/slides/slide-1", (self.root / "public/_redirects").read_text())

    def test_drafts_stay_out_of_pages_lists_and_feed(self):
        self.create()
        self.project.build()
        self.assertFalse((self.root / "public/first").exists())
        self.assertNotIn("A living portfolio", (self.root / "public/index.html").read_text())
        self.assertNotIn("A living portfolio", (self.root / "public/talks/index.html").read_text())
        self.project.mark_ready("first")
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
        (self.project.asset_dir / deck["slides"][0]["image"]).write_bytes(b"changed")
        with self.assertRaisesRegex(PortfolioError, "Immutable asset was modified"):
            self.project.check()

    def test_comments_and_markdown_survive_recording_update(self):
        self.create()
        path = self.project.appearance("first")[0]
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
        (self.project.asset_dir / deck["pdf"]).unlink()
        with self.assertRaisesRegex(PortfolioError, "Missing local asset"):
            self.project.build()
        with self.assertRaisesRegex(PortfolioError, "Missing local asset"):
            self.project.build(local=True)

    def test_production_downloads_use_readable_names_and_pinned_git_urls(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        self.project.build()
        html = (self.root / "public/first/index.html").read_text()
        self.assertIn("https://raw.githubusercontent.com/phrawzty/assets.dark.ca/", html)
        self.assertIn("/files/decks/2020-01-01-workflow-example-example-event/2020-01-01-workflow-example-example-event.pdf", html)
        self.assertNotIn("releases/download", html)
        self.assertFalse(list((self.root / "public/assets").rglob("*.pdf")))

    def test_shared_pdf_and_images_are_staged_once_across_display_versions(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        self.create("second", publish=True)
        deck = self.project.deck(self.v1)
        deck["id"] = "alternate-display"
        (self.root / "data/decks/alternate-display.json").write_text(json.dumps(deck))
        path, meta, body = self.project.appearance("second")
        meta["extra"]["deck"] = "alternate-display"
        write_page(path, meta, body)
        self.project.build(local=True)
        preview_pdf = self.root / ".portfolio/preview/assets" / deck["pdf"]
        self.assertEqual(preview_pdf.read_bytes(), (self.project.asset_dir / deck["pdf"]).read_bytes())
        self.project.build()
        self.assertTrue((self.root / "public/first/index.html").exists())
        self.assertTrue((self.root / "public/second/index.html").exists())

    def test_editing_title_keeps_existing_bundle_paths_and_reuses_processing(self):
        self.create(publish=True)
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        before = self.project.deck(self.v1)
        path, meta, body = self.project.appearance("first")
        meta["title"] = "A corrected title"
        write_page(path, meta, body)
        with patch("portfolio.cli.run", side_effect=AssertionError("Cached slides must not be processed again")):
            self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        self.assertEqual(before, self.project.deck(self.v1))

    def test_temporary_host_base_url_controls_navigation_and_keeps_drafts_private(self):
        self.create(publish=True)
        self.create("private-draft")
        with patch.dict(os.environ, {"PORTFOLIO_BASE_URL": "https://portfolio-test.pages.dev"}):
            self.call("build")
        html = (self.root / "public/index.html").read_text()
        self.assertIn('href="https://portfolio-test.pages.dev/talks/"', html)
        self.assertNotIn('href="https://portfolio.dark.ca/talks/"', html)
        self.assertFalse((self.root / "public/private-draft").exists())
        self.call("build", "--base-url", "https://explicit-test.pages.dev")
        self.assertIn('href="https://explicit-test.pages.dev/talks/"', (self.root / "public/index.html").read_text())

    def test_revised_pdf_gets_readable_version_suffix(self):
        first = self.project.deck(self.v1)["pdf"]
        second = self.project.deck(self.v2)["pdf"]
        self.assertTrue(first.endswith("example-event.pdf"))
        self.assertTrue(second.endswith("example-event-v2.pdf"))
        self.assertNotIn(self.v1, first)
        self.assertEqual(Path(first).parent.name, Path(first).stem)
        self.assertEqual(Path(second).parent.name, Path(second).stem)
        for version in (self.v1, self.v2):
            deck = self.project.deck(version)
            self.assertEqual(Path(deck["slides"][0]["image"]).parent.parent, Path(deck["pdf"]).parent)
            self.assertEqual(Path(deck["slides"][0]["image"]).name, "001.webp")

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
        path = self.project.appearance("first")[0]
        meta, body = read_page(path)
        meta["extra"]["resources"] = [{"title": "Missing", "url": "/does-not-exist/"}]
        write_page(path, meta, body)
        with self.assertRaisesRegex(PortfolioError, "Broken internal links"):
            self.project.build()

    def test_chooser_searches_by_event_without_needing_an_id(self):
        self.create("first")
        self.create("second")
        path = self.project.appearance("second")[0]
        meta, body = read_page(path)
        meta["extra"]["event"] = "A specific conference"
        write_page(path, meta, body)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["specific", "1"]):
            self.assertEqual(self.project.choose_appearance(), "second")

    def test_add_slides_with_only_interactive_prompts(self):
        self.create()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["1", '"' + str(SOURCE / "tests/fixtures/deck-v1.pdf") + '"']):
            self.call("slides")
        self.assertEqual(read_page(self.project.appearance("first")[0])[0]["extra"]["deck"], self.v1)

    def test_markdown_path_works_for_noninteractive_commands(self):
        self.create()
        self.call("slides", str(self.project.appearance("first")[0].relative_to(self.project.root)), str(SOURCE / "tests/fixtures/deck-v1.pdf"))
        self.assertEqual(read_page(self.project.appearance("first")[0])[0]["extra"]["deck"], self.v1)

    def test_menu_creates_a_draft_and_opens_its_markdown(self):
        answers = ["1", "A new talk", "Another event", "2031-02-03", "Paris, France", "", "q"]
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
        previous = (self.project.appearance("first")[0]).read_bytes()
        answers = ["1", "", "Another event", "2031-02-03", "Paris, France", ""]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=answers), patch.object(Portfolio, "open_editor"):
            self.call("repeat")
        meta, _ = read_page(self.root / "content/appearances/2031-02-03-another-event.md")
        self.assertEqual(meta["extra"]["deck"], "")
        self.assertEqual(meta["extra"]["recording_url"], "")
        self.assertEqual((self.project.appearance("first")[0]).read_bytes(), previous)

    def test_repeat_can_explicitly_reuse_previous_slides(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        answers = ["1", "", "Another event", "2031-02-03", "Paris, France", "reuse"]
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
        path = self.project.appearance("first")[0]
        before = path.read_bytes()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=""):
            self.call("recording")
        self.assertEqual(path.read_bytes(), before)

    def test_remove_appearance_requires_confirmation_and_keeps_shared_content(self):
        self.create("first", publish=True)
        path, meta, _ = self.project.appearance("first")
        talk = self.root / "content/talks" / (meta["extra"]["talk"] + ".md")
        deck = self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        deck_path = self.root / "data/decks" / (deck + ".json")

        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="no"):
            self.call("remove", "first")
        self.assertTrue(path.exists())

        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="remove"):
            self.call("remove", "first")
        self.assertFalse(path.exists())
        self.assertTrue(talk.exists())
        self.assertTrue(deck_path.exists())
        self.assertTrue((self.root / "data/places.toml").exists())

    def test_remove_requires_yes_without_a_terminal(self):
        self.create()
        path = self.project.appearance("first")[0]
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(main(["--root", str(self.root), "remove", "first"]), 1)
        self.assertTrue(path.exists())
        self.assertIn("without --yes", errors.getvalue())

        self.call("remove", "first", "--yes")
        self.assertFalse(path.exists())

    def test_menu_removes_a_cancelled_appearance(self):
        self.create()
        path = self.project.appearance("first")[0]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["10", "1", "remove", "q"]):
            self.assertEqual(main(["--root", str(self.root)]), 0)
        self.assertFalse(path.exists())

    def test_url_alone_uses_the_recording_chooser(self):
        self.create()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["1"]):
            self.call("recording", "https://example.com/recording")
        meta, _ = read_page(self.project.appearance("first")[0])
        self.assertEqual(meta["extra"]["recording_url"], "https://example.com/recording")

    def test_publication_menu_lists_only_drafts(self):
        self.create("published", publish=True)
        self.create("draft")
        path = self.project.appearance("published")[0]
        meta, body = read_page(path)
        meta["title"] = "Already published talk"
        write_page(path, meta, body)
        output = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["8", "1", "q"]), patch.object(Portfolio, "publish") as publish, contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root)]), 0)
        self.assertIn("Choose a draft", output.getvalue())
        self.assertNotIn("Already published talk", output.getvalue())
        publish.assert_called_once_with("draft")

    def test_publication_with_no_drafts_publishes_current_changes(self):
        self.create(publish=True)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=AssertionError("There is nothing to choose")), patch.object(Portfolio, "publish") as publish:
            self.assertEqual(main(["--root", str(self.root), "publish"]), 0)
        publish.assert_called_once_with(None, yes=False)

    def test_publish_marks_a_draft_builds_commits_and_pushes(self):
        self.create("draft")
        portfolio_remote, _ = self.initialize_publish_repositories()
        self.call("publish", "draft", "--yes")
        self.assertFalse(read_page(self.project.appearance("draft")[0])[0]["draft"])
        local = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip()
        remote = subprocess.check_output(["git", "--git-dir", str(portfolio_remote), "rev-parse", "main"]).decode().strip()
        subject = subprocess.check_output(["git", "-C", str(self.root), "log", "-1", "--format=%s"]).decode().strip()
        self.assertEqual(local, remote)
        self.assertEqual(subject, "Publish Example event")
        self.assertTrue((self.root / "public/draft/index.html").exists())

    def test_publish_existing_text_skips_assets(self):
        self.create("published", publish=True)
        portfolio_remote, _ = self.initialize_publish_repositories()
        assets_before = subprocess.check_output(["git", "-C", str(self.project.asset_repository.checkout), "rev-parse", "HEAD"]).decode().strip()
        path, meta, body = self.project.appearance("published")
        meta["title"] = "A corrected title"
        write_page(path, meta, body)
        self.call("publish", "--yes")
        portfolio_head = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip()
        remote_head = subprocess.check_output(["git", "--git-dir", str(portfolio_remote), "rev-parse", "main"]).decode().strip()
        assets_after = subprocess.check_output(["git", "-C", str(self.project.asset_repository.checkout), "rev-parse", "HEAD"]).decode().strip()
        self.assertEqual(portfolio_head, remote_head)
        self.assertEqual(assets_before, assets_after)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "log", "-1", "--format=%s"]).decode().strip(), "Update speaking portfolio")

    def test_publish_detects_and_pushes_referenced_assets_first(self):
        self.create("published", publish=True)
        portfolio_remote, assets_remote = self.initialize_publish_repositories()
        asset = self.project.asset_dir / "speaker/publish-test.jpg"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"new published headshot")
        bundle = {"files": [{"path": "speaker/publish-test.jpg", "bytes": asset.stat().st_size, "sha256": sha256(asset)}]}
        (self.root / "data/site-assets.json").write_text(json.dumps(bundle))
        self.call("publish", "--yes")
        locked = json.loads((self.root / "data/assets-lock.json").read_text())["revision"]
        assets_remote_head = subprocess.check_output(["git", "--git-dir", str(assets_remote), "rev-parse", "main"]).decode().strip()
        portfolio_remote_head = subprocess.check_output(["git", "--git-dir", str(portfolio_remote), "rev-parse", "main"]).decode().strip()
        self.assertEqual(locked, assets_remote_head)
        self.assertEqual(portfolio_remote_head, subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip())
        self.assertIn("speaker/publish-test.jpg", subprocess.check_output(["git", "--git-dir", str(assets_remote), "ls-tree", "-r", "--name-only", "main"]).decode())

    def test_publish_decline_leaves_changes_uncommitted_and_unpushed(self):
        self.create("published", publish=True)
        portfolio_remote, _ = self.initialize_publish_repositories()
        before = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip()
        path, meta, body = self.project.appearance("published")
        meta["title"] = "A corrected title"
        write_page(path, meta, body)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
            self.assertEqual(main(["--root", str(self.root), "publish"]), 0)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip(), before)
        self.assertEqual(subprocess.check_output(["git", "--git-dir", str(portfolio_remote), "rev-parse", "main"]).decode().strip(), before)
        self.assertIn("A corrected title", path.read_text())

    def test_publish_decline_restores_selected_draft(self):
        self.create("draft")
        self.initialize_publish_repositories()
        before = self.project.appearance("draft")[0].read_bytes()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
            self.assertEqual(main(["--root", str(self.root), "publish", "draft"]), 0)
        self.assertEqual(self.project.appearance("draft")[0].read_bytes(), before)
        self.assertTrue(read_page(self.project.appearance("draft")[0])[0]["draft"])

    def test_publish_resumes_a_prepared_commit_after_push_failure(self):
        self.create("published", publish=True)
        portfolio_remote, _ = self.initialize_publish_repositories()
        path, meta, body = self.project.appearance("published")
        meta["title"] = "A corrected title"
        write_page(path, meta, body)
        subprocess.run(["git", "-C", str(self.root), "remote", "set-url", "origin", str(self.root / "missing-remote.git")], check=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--root", str(self.root), "publish", "--yes"]), 1)
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "rev-list", "--count", "@{upstream}..HEAD"]).decode().strip(), "1")
        subprocess.run(["git", "-C", str(self.root), "remote", "set-url", "origin", str(portfolio_remote)], check=True)
        self.call("publish", "--yes")
        self.assertEqual(subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"]).decode().strip(),
                         subprocess.check_output(["git", "--git-dir", str(portfolio_remote), "rev-parse", "main"]).decode().strip())

    def test_check_report_explains_success_scope_and_draft_counts(self):
        self.create("draft")
        self.create("published", publish=True)
        self.project.attach_pdf("draft", SOURCE / "tests/fixtures/deck-v1.pdf")
        before = (self.project.appearance("draft")[0]).read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--root", str(self.root), "check"]), 0)
        report = output.getvalue()
        self.assertIn("PASS — portfolio consistency checks completed", report)
        self.assertIn("2 appearances: 1 draft, 1 included in production builds", report)
        self.assertIn("sizes and checksums", report)
        self.assertIn("external URL availability", report)
        self.assertIn("No files were changed or uploaded", report)
        self.assertEqual((self.project.appearance("draft")[0]).read_bytes(), before)

    def test_failed_check_names_the_talk_and_problem_without_claiming_success(self):
        self.create()
        self.project.attach_pdf("first", SOURCE / "tests/fixtures/deck-v1.pdf")
        deck = self.project.deck(self.v1)
        (self.project.asset_dir / deck["slides"][0]["image"]).unlink()
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
