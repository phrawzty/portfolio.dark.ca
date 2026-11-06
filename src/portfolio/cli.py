"""Author appearances, process versioned decks, preview, and publish static assets."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import fcntl
from html.parser import HTMLParser
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import unicodedata
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import Image
import tomlkit
from pypdf import PdfReader
from portfolio.assets import AssetRepository

DEFAULT_ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
PAGE_LIMIT = 25 * 1024 * 1024


class PortfolioError(ValueError):
    pass


class UserCancelled(Exception):
    pass


def prompt(prompt_text, default="", required=True):
    if not sys.stdin.isatty():
        raise PortfolioError(f"{prompt_text}: run in a terminal to be prompted, or supply the command arguments")
    while True:
        value = input(prompt_text + (f" [{default}]" if default else "") + ": ").strip() or default
        if value or not required:
            return value
        print("Please enter a value, or press Ctrl-C to cancel.")


def pdf_path(value):
    """Accept a typed path, quoted path, or a path dragged into a terminal."""
    value = value.strip()
    direct = Path(value).expanduser()
    if direct.is_file():
        return direct
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = []
    return Path(parts[0]).expanduser() if len(parts) == 1 else direct


def read_page(path: Path):
    source = path.read_text()
    match = re.match(r"\A\+\+\+\s*\n(.*?)\n\+\+\+\s*\n?(.*)\Z", source, re.S)
    if not match:
        raise PortfolioError(f"Missing TOML front matter: {path}")
    try:
        metadata = tomlkit.parse(match[1])
    except tomlkit.exceptions.ParseError as error:
        raise PortfolioError(f"{path}: {error}") from error
    return metadata, match[2]


def write_page(path, metadata, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("+++\n" + tomlkit.dumps(metadata).rstrip() + "\n+++\n\n" + body.lstrip())


def json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def sha256(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def slug(text):
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "talk"


def identifier(value):
    if not IDENTIFIER.fullmatch(value):
        raise PortfolioError(f"Invalid ID: {value!r}; use letters, digits, hyphens, or underscores")
    return value


def run(command, **kwargs):
    try:
        return subprocess.run([str(x) for x in command], check=True, **kwargs)
    except FileNotFoundError as error:
        raise PortfolioError(f"Missing command {command[0]!r}. Run 'portfolio doctor' for setup instructions.") from error
    except subprocess.CalledProcessError as error:
        raise PortfolioError(f"Command failed: {shlex.join([str(x) for x in command])}") from error


class Portfolio:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if not (self.root / "zola.toml").is_file():
            raise PortfolioError(f"Not a portfolio checkout: {self.root}")
        self.settings = tomllib.loads((self.root / "portfolio.toml").read_text())
        self.asset_dir = (self.root / self.settings.get("assets", {}).get("directory", "../assets.dark.ca/files")).resolve()
        self.asset_repository = AssetRepository(self)

    def appearances(self, include_drafts=True):
        result = []
        for path in sorted((self.root / "content/appearances").glob("*.md")):
            if path.name == "_index.md":
                continue
            meta, body = read_page(path)
            if include_drafts or not meta.get("draft", False):
                result.append((path, meta, body))
        return result

    def appearance(self, ident):
        # Paths printed by the editor or selected in a file manager also work.
        supplied = Path(ident).expanduser()
        if supplied.suffix == ".md":
            path = supplied if supplied.is_absolute() else self.root / supplied
            path = path.resolve()
            if path.parent != (self.root / "content/appearances").resolve():
                raise PortfolioError("Choose a Markdown file in content/appearances/")
        else:
            path = self.root / "content/appearances" / (identifier(ident) + ".md")
        if not path.is_file():
            raise PortfolioError(f"Unknown appearance {ident!r}")
        return path, *read_page(path)

    def choose_appearance(self, value=None, *, drafts_only=False):
        if value:
            return self.appearance(value)[1]["extra"]["id"]
        if not sys.stdin.isatty():
            raise PortfolioError("Choose a talk interactively in a terminal, or supply its Markdown path or ID for scripting")
        entries = sorted(self.appearances(), key=lambda item: item[1]["date"].isoformat(), reverse=True)
        if drafts_only:
            entries = [item for item in entries if item[1].get("draft", False)]
        if not entries:
            if drafts_only:
                raise UserCancelled("No drafts waiting for publication.")
            raise PortfolioError("No talks yet. Choose 'New talk' or run 'portfolio new' first.")
        query = ""
        while True:
            matches = [item for item in entries if query.casefold() in " ".join((str(item[1]["date"]), item[1]["title"], item[1]["extra"]["event"], item[1]["extra"]["location"])).casefold()]
            shown = matches[:10]
            print(("\nChoose a draft" if drafts_only else "\nChoose a talk") + (f" matching {query!r}" if query else "") + ":")
            for number, (_, meta, _) in enumerate(shown, 1):
                draft = " · draft" if meta.get("draft") else ""
                print(f"  {number}. {meta['title']} — {meta['extra']['event']} — {str(meta['date'])[:10]}{draft}")
            if len(matches) > len(shown):
                print(f"  Showing {len(shown)} of {len(matches)}. Search to narrow the list.")
            if not shown:
                print("  No matches. Try another title, event, city, or year.")
            choice = input("Number, search text, or Enter to cancel: ").strip()
            if not choice or choice.casefold() in ("q", "quit"):
                raise UserCancelled()
            if choice.isdigit() and 1 <= int(choice) <= len(shown):
                return shown[int(choice) - 1][1]["extra"]["id"]
            query = choice

    def open_editor(self, path):
        print("Edit: " + str(path.relative_to(self.root)))
        if not sys.stdin.isatty():
            return
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if editor:
            run([*shlex.split(editor), path])
        elif sys.platform == "darwin":
            run(["open", "-t", path])
        elif shutil.which("xdg-open"):
            run(["xdg-open", path])
        else:
            print("Open this file in your preferred text editor.")

    def edit(self, ident):
        self.open_editor(self.appearance(ident)[0])

    def deck(self, ident):
        identifier(ident)
        path = self.root / "data/decks" / (ident + ".json")
        if not path.is_file():
            raise PortfolioError(f"Missing deck metadata: {ident}")
        return json.loads(path.read_text())

    def bundles(self, include_drafts=True):
        ids = {m["extra"].get("deck") for _, m, _ in self.appearances(include_drafts)} - {None, ""}
        result = [self.deck(ident) for ident in sorted(ids)]
        shared = self.root / "data/site-assets.json"
        if shared.exists():
            result.append(json.loads(shared.read_text()))
        return result

    def new(self, args):
        previous = self.appearance(args.from_appearance) if args.from_appearance else None
        if args.reuse_slides and not previous:
            raise PortfolioError("--reuse-slides requires --from")
        prior = previous[1] if previous else {}
        prior_extra = prior.get("extra", {})

        def answer(value, prompt, default=""):
            if value is not None:
                return value
            if sys.stdin.isatty():
                while True:
                    response = input(prompt + (f" [{default}]" if default else "") + ": ").strip() or default
                    if response:
                        return response
                    print("Please enter a value, or press Ctrl-C to cancel.")
            if default:
                return default
            raise PortfolioError(f"{prompt} is required; supply the corresponding option")

        title = answer(args.title, "Talk title", prior.get("title", ""))
        event = answer(args.event, "Event name")
        event_date = date.fromisoformat(answer(args.date, "Event date (YYYY-MM-DD)"))
        location = answer(args.location, "Location (city, country; or Virtual)")
        if args.timezone is not None:
            try:
                ZoneInfo(args.timezone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise PortfolioError(f"Unknown timezone: {args.timezone}") from error
        ident = identifier(args.id or f"{event_date.isoformat()}-{slug(event)}")
        destination = self.root / "content/appearances" / (ident + ".md")
        if not args.id:
            base_ident = ident
            number = 2
            while destination.exists():
                ident = base_ident + "-" + str(number)
                destination = destination.with_name(ident + ".md")
                number += 1
        if destination.exists():
            raise PortfolioError(f"Appearance {ident} already exists; choose --id for another talk at this event")
        talk_id = identifier(args.talk or prior_extra.get("talk", slug(title)))
        talk_path = self.root / "content/talks" / (talk_id + ".md")
        if not talk_path.exists():
            talk_meta = tomlkit.document()
            talk_meta.update(title=title, template="talk.html", draft=not args.publish)
            write_page(talk_path, talk_meta, "Write the reusable talk description here.\n")
        talk_meta, talk_body = read_page(talk_path)
        if args.publish and talk_meta.get("draft"):
            talk_meta["draft"] = False
            write_page(talk_path, talk_meta, talk_body)
        meta = tomlkit.document()
        meta.update(title=title, date=event_date, draft=not args.publish, path=ident, template="appearance.html")
        extra = tomlkit.table()
        extra.update(id=ident, talk=talk_id, event=event, event_url=args.event_url or "", location=location,
                     virtual=location.casefold() in ("virtual", "online"),
                     deck=prior_extra.get("deck", "") if args.reuse_slides else "", recording_url="")
        if args.timezone is not None:
            extra["timezone"] = args.timezone
        # Resources may be reused; reactions and recordings belong to their event.
        if previous and prior_extra.get("resources"):
            extra["resources"] = prior_extra["resources"]
        meta["extra"] = extra
        write_page(destination, meta, previous[2] if previous else talk_body)
        print(destination.relative_to(self.root))
        print("Created. Edit the Markdown, or run 'portfolio slides' to choose this talk and add a PDF.")
        return ident

    def deck_directory_for(self, meta):
        """Allocate a readable version folder once; subsequent edits keep its name."""
        base = f"{str(meta['date'])[:10]}-{slug(meta['title'])[:90]}-{slug(meta['extra']['event'])[:60]}"
        number = 1
        while True:
            relative = "decks/" + base + (f"-v{number}" if number > 1 else "")
            if not (self.asset_dir / relative).exists():
                return relative
            number += 1

    def attach_pdf(self, ident, source):
        page_path, meta, body = self.appearance(ident)
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise PortfolioError(f"PDF not found: {source}")
        with source.open("rb") as stream:
            if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                raise PortfolioError("The input is not a PDF")
        version = sha256(source)
        deck_path = self.root / "data/decks" / (version + ".json")
        if deck_path.exists():
            deck = self.deck(version)
            self.verify_assets(deck)
            print("Reusing processed deck " + version[:12])
        else:
            prefix = self.deck_directory_for(meta)
            destination = self.asset_dir / prefix
            if destination.exists():
                raise PortfolioError(f"Unregistered asset directory exists: {destination}; inspect it before retrying")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="process-", dir=self.root / ".portfolio") as temporary:
                temporary = Path(temporary)
                copied = temporary / "original.pdf"
                shutil.copy2(source, copied)
                info = run(["pdfinfo", copied], capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
                match = re.search(r"^Pages:\s+(\d+)", info.stdout, re.M)
                if not match:
                    raise PortfolioError("Could not determine PDF page count")
                expected = int(match[1])
                # Extract each page independently to keep blank-page positions stable.
                reader = PdfReader(copied)
                if reader.is_encrypted:
                    raise PortfolioError("Export an unencrypted PDF before adding it to the public portfolio")
                texts = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
                if len(texts) != expected:
                    raise PortfolioError(f"Text page count {len(texts)} differs from PDF page count {expected}")
                rendered = run(["pdftoppm", "-scale-to", "1600", "-png", copied, temporary / "page"], capture_output=True, text=True)
                images = sorted(temporary.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
                if len(images) != expected:
                    raise PortfolioError("PDF did not render completely")
                (temporary / "slides").mkdir()
                slides = []
                for number, image_path in enumerate(images, 1):
                    filename = f"{number:03d}.webp"
                    with Image.open(image_path) as image:
                        image.load()
                        image.save(temporary / "slides" / filename, format="WEBP", lossless=True, method=6)
                        width, height = image.size
                    image_path.unlink()
                    slides.append({"id": f"slide-{number}", "number": number, "image": prefix + "/slides/" + filename,
                                   "width": width, "height": height, "text": texts[number - 1].strip(), "title": ""})
                # Recheck the source copy before atomically registering this version.
                if sha256(copied) != version:
                    raise PortfolioError("Source PDF changed while being processed")
                pdf_name = Path(prefix).name + ".pdf"
                pdf_relative = prefix + "/" + pdf_name
                copied.rename(temporary / pdf_name)
                deck = {"id": version, "source_sha256": version, "source_filename": source.name, "provenance": "original",
                        "pdf": pdf_relative, "slides": slides, "page_count": expected,
                        "processor": "poppler-1600-webp-lossless-v1", "processing_warnings": (info.stderr + rendered.stderr).strip()}
                deck["files"] = [{"path": prefix + "/" + str(file.relative_to(temporary)), "bytes": file.stat().st_size, "sha256": sha256(file)}
                                 for file in sorted(temporary.rglob("*")) if file.is_file()]
                shutil.move(str(temporary), destination)
                json_file(deck_path, deck)
                print(f"Processed all {expected} pages into deck {version[:12]}")
        meta["extra"]["deck"] = version
        write_page(page_path, meta, body)
        print(f"Attached to {ident}; previous appearances and deck versions are unchanged.")
        return version

    def recording(self, ident, url):
        validate_url(url)
        path, meta, body = self.appearance(ident)
        meta["extra"]["recording_url"] = url
        write_page(path, meta, body)
        print(f"Recording added to {ident}")

    def notes(self, ident):
        _, meta, _ = self.appearance(ident)
        deck_id = meta["extra"].get("deck")
        if not deck_id:
            raise PortfolioError("Add a deck before editing its slide notes")
        destination = self.root / "notes" / (deck_id + ".toml")
        if not destination.exists():
            document = tomlkit.document()
            document.add(tomlkit.comment("Editable titles and transcriptions for this deck version; source PDF and images stay unchanged."))
            entries = tomlkit.aot()
            for slide in self.deck(deck_id)["slides"]:
                entry = tomlkit.table()
                entry.update(id=slide["id"], title=slide.get("title", ""))
                entry["text"] = tomlkit.string(slide["text"], multiline=True)
                entries.append(entry)
            document["slide"] = entries
            destination.parent.mkdir(exist_ok=True)
            destination.write_text(tomlkit.dumps(document))
        self.open_editor(destination)

    def with_notes(self, deck):
        path = self.root / "notes" / (deck["id"] + ".toml")
        if not path.exists():
            return deck
        overrides = tomllib.loads(path.read_text()).get("slide", [])
        by_id = {s["id"]: s for s in deck["slides"]}
        seen = set()
        for override in overrides:
            ident = override.get("id")
            if ident not in by_id or ident in seen:
                raise PortfolioError(f"Unknown or duplicate slide ID in {path.name}: {ident}")
            seen.add(ident)
            for key in ("title", "text"):
                if key in override:
                    if not isinstance(override[key], str):
                        raise PortfolioError(f"{path.name}: {key} must be text")
                    by_id[ident][key] = override[key]
        return deck

    def publish(self, ident):
        path, meta, body = self.appearance(ident)
        meta["draft"] = False
        # Validate before saving the public state.
        self.validate_page(path, meta)
        if meta["extra"].get("deck"):
            self.verify_assets(self.deck(meta["extra"]["deck"]))
        write_page(path, meta, body)
        talk_path = self.root / "content/talks" / (meta["extra"]["talk"] + ".md")
        talk_meta, talk_body = read_page(talk_path)
        talk_meta["draft"] = False
        write_page(talk_path, talk_meta, talk_body)
        print(f"{ident} is now included in production builds. Commit and push when ready.")

    def places(self):
        path = self.root / "data/places.toml"
        return tomllib.loads(path.read_text()).get("place", []) if path.exists() else []

    def coordinates(self, extra):
        if extra.get("virtual"):
            return None
        if extra.get("latitude") is not None and extra.get("longitude") is not None:
            return float(extra["latitude"]), float(extra["longitude"])
        match = next((p for p in self.places() if p["name"].casefold() == extra.get("location", "").casefold()), None)
        return (float(match["lat"]), float(match["lng"])) if match else None

    def place(self, name, map_url):
        parsed = urlparse(map_url)
        if parsed.hostname not in ("www.openstreetmap.org", "openstreetmap.org"):
            raise PortfolioError("Use an OpenStreetMap link containing #map=zoom/latitude/longitude")
        match = re.search(r"(?:^|&)map=[^/]+/(-?[\d.]+)/(-?[\d.]+)", parsed.fragment)
        if not match:
            raise PortfolioError("The map URL must include #map=zoom/latitude/longitude")
        lat, lng = map(float, match.groups())
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise PortfolioError("Invalid map coordinates")
        path = self.root / "data/places.toml"
        document = tomlkit.parse(path.read_text())
        places = document.get("place", tomlkit.aot())
        existing = next((p for p in places if p["name"].casefold() == name.casefold()), None)
        entry = existing if existing is not None else tomlkit.table()
        entry.update(name=name, lat=lat, lng=lng)
        if existing is None:
            places.append(entry)
        document["place"] = places
        path.write_text(tomlkit.dumps(document))
        print(f"Saved {name}; matching appearances will be mapped automatically.")

    def verify_assets(self, deck, production=False):
        for item in deck["files"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts:
                raise PortfolioError("Asset path escapes the asset directory")
            path = self.asset_dir / relative
            if path.exists():
                if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
                    raise PortfolioError(f"Immutable asset was modified: {relative}")
            else:
                raise PortfolioError(f"Missing local asset: {relative}. Restore the assets Git checkout or add the missing file.")
            if production and item["path"] != deck.get("pdf") and item["bytes"] > PAGE_LIMIT:
                raise PortfolioError(f"{relative} exceeds Pages' 25 MiB image limit")

        if production:
            self.asset_repository.verify_committed(deck)

    def validate_page(self, path, meta):
        extra = meta.get("extra", {})
        for key in ("id", "talk", "event", "location"):
            if not extra.get(key):
                raise PortfolioError(f"{path.name}: extra.{key} is required")
        if extra["id"] != path.stem or meta.get("path") != extra["id"]:
            raise PortfolioError(f"{path.name}: filename, extra.id, and path must agree")
        identifier(extra["id"])
        identifier(extra["talk"])
        if not meta.get("title") or not isinstance(meta.get("date"), (date, datetime)):
            raise PortfolioError(f"{path.name}: title and TOML date are required")
        if not (self.root / "content/talks" / (extra["talk"] + ".md")).is_file():
            raise PortfolioError(f"{path.name}: missing talk {extra['talk']}")
        if "timezone" in extra:
            try:
                ZoneInfo(extra["timezone"])
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise PortfolioError(f"{path.name}: unknown timezone") from error
        for key in ("event_url", "recording_url"):
            if extra.get(key):
                validate_url(extra[key])
        for resource in extra.get("resources", []):
            if not resource.get("title"):
                raise PortfolioError(f"{path.name}: resource title is required")
            validate_url(resource.get("url", ""), allow_local=True)
        for feedback in extra.get("feedback", []):
            if not feedback.get("text"):
                raise PortfolioError(f"{path.name}: feedback text is required")
            if feedback.get("url"):
                validate_url(feedback["url"])
        coords = self.coordinates(extra)
        if coords and not (-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180):
            raise PortfolioError(f"{path.name}: invalid coordinates")
        if (extra.get("latitude") is None) != (extra.get("longitude") is None):
            raise PortfolioError(f"{path.name}: supply both latitude and longitude")

    def check(self, production=False, *, report=False):
        context = "Reading talk metadata"
        if report:
            scope = "production content and asset configuration" if production else "local portfolio, including drafts"
            print(f"Checking {scope}...", flush=True)
        try:
            appearances = self.appearances(include_drafts=not production)
            deck_owners = {}
            routes = {"", "appearances", "talks", "videos", "bio"}
            for path, meta, body in appearances:
                context = str(path.relative_to(self.root))
                self.validate_page(path, meta)
                ident = meta["extra"]["id"]
                for route in [meta["path"], *meta.get("aliases", []), ident + "/slides", ident + "/present"]:
                    normalized = route.strip("/")
                    if normalized in routes:
                        raise PortfolioError(f"Duplicate output route: {normalized}")
                    routes.add(normalized)
                deck_id = meta["extra"].get("deck")
                if deck_id:
                    deck_owners.setdefault(deck_id, meta["title"] + " — " + meta["extra"]["event"])
            if report:
                print(f"  OK  Required details, dates, timezones, URL formatting and unique page URLs ({len(appearances)} appearances)", flush=True)
                print("  Checking slide references and editable notes...", flush=True)
            bundles = []
            for deck_id, owner in deck_owners.items():
                context = "Slides for " + owner
                deck = self.deck(deck_id)
                self.with_notes(deck)
                if deck["id"] != deck_id or deck["page_count"] != len(deck["slides"]):
                    raise PortfolioError(f"Deck {deck_id} has inconsistent page metadata")
                registered = {item["path"] for item in deck["files"]}
                for slide in deck["slides"]:
                    if slide["image"] not in registered:
                        raise PortfolioError(f"Deck {deck_id} references an unregistered slide image")
                bundles.append((owner, deck))
            if report:
                print(f"  OK  Slide references and editable notes ({len(deck_owners)} deck versions)", flush=True)
                label = "local assets and the pinned Git commit" if production else "local asset files (sizes and checksums)"
                print(f"  Checking {label}...", flush=True)
            shared = self.root / "data/site-assets.json"
            if shared.exists():
                context = "Shared site assets (data/site-assets.json)"
                bundles.append(("Shared site assets", json.loads(shared.read_text())))
            files = {}
            for owner, bundle in bundles:
                context = "Assets for " + owner
                self.verify_assets(bundle, production=production)
                for item in bundle["files"]:
                    files[item["path"]] = item
            if report:
                suffix = "match their saved checksums and the recorded assets commit" if production else "match their saved sizes and checksums"
                noun = "asset records" if production else "asset files"
                print(f"  OK  {len(files):,} {noun} {suffix}", flush=True)
        except (PortfolioError, ValueError, KeyError, OSError) as error:
            if report:
                print("\nFAIL — the check stopped at the first problem.", flush=True)
                print("Remaining checks have not completed. No files were changed or uploaded.", flush=True)
            raise PortfolioError(f"{context}: {error}\nFix this item, then run the check again.") from error
        if report:
            drafts = sum(bool(meta.get("draft", False)) for _, meta, _ in appearances)
            print("\nPASS — portfolio consistency checks completed.")
            draft_label = "draft" if drafts == 1 else "drafts"
            print(f"{len(appearances)} appearances: {drafts} {draft_label}, {len(appearances) - drafts} included in production builds.")
            print("No files were changed or uploaded.")
            print("Not checked: external URL availability, visual layout, or PDF page rendering.")
            if not production:
                print("Deployment readiness is checked separately by the production build.")
            print("Next: choose Preview to review the site.")
        else:
            print(f"Checked {len(appearances)} appearances and {len(deck_owners)} deck versions.")
        return appearances

    def prepare_site(self, local=False):
        self.check(production=not local)
        staging = self.root / ".portfolio/site"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        for name in ("content", "data", "templates", "themes", "static", "sass"):
            if (self.root / name).exists():
                shutil.copytree(self.root / name, staging / name)
        for deck in self.bundles(include_drafts=local):
            if deck.get("slides"):
                display = self.with_notes(deck)
                display["pdf_url"] = ("/assets/" + deck["pdf"] if local else self.asset_repository.pdf_url(deck["pdf"])) if deck.get("pdf") else ""
                json_file(staging / "data/decks" / (deck["id"] + ".json"), display)
        config = tomlkit.parse((self.root / "zola.toml").read_text())
        config["extra"]["asset_base"] = "/assets"
        config["extra"]["preview"] = local
        (staging / "zola.toml").write_text(tomlkit.dumps(config))
        appearances = self.appearances(include_drafts=local)
        for deck in self.bundles(include_drafts=local):
            self.verify_assets(deck, production=not local)
            for item in deck["files"]:
                if not local and item["path"] == deck.get("pdf"):
                    continue
                source = self.asset_dir / item["path"]
                destination = staging / "static/assets" / item["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    continue  # Multiple display versions can reference one immutable file.
                try:
                    os.link(source, destination)
                except OSError:
                    shutil.copyfile(source, destination)
        points = []
        # Pages accepts path redirects; the hostname redirect is a zone rule.
        redirects = ["/presentations /appearances/ 301"]
        generated = staging / "content/generated"
        generated.mkdir()
        (generated / "_index.md").write_text('+++\nrender = false\ntransparent = true\n+++\n')
        for _, meta, body in appearances:
            extra = meta["extra"]
            for alias in meta.get("aliases", []):
                redirects.append(f"/{alias.strip('/')} /{extra['id']}/ 301")
            for view in ("slides", "present"):
                if not extra.get("deck"):
                    continue
                child = tomlkit.parse(tomlkit.dumps(meta))
                child["path"] = extra["id"] + "/" + view
                child["template"] = "slides.html" if view == "slides" else "present.html"
                child["hidden"] = True
                child["in_search_index"] = False
                child["include_in_feeds"] = False
                child.pop("aliases", None)
                write_page(generated / (extra["id"] + "-" + view + ".md"), child, body)
            coordinates = self.coordinates(extra)
            if coordinates:
                points.append({"lat": coordinates[0], "lng": coordinates[1], "title": meta["title"],
                               "event": extra["event"], "location": extra["location"], "url": "/" + extra["id"] + "/"})
        json_file(staging / "static/appearances-map.json", {"points": points, "tiles": self.settings.get("map", {}).get("tiles", ""), "attribution": self.settings.get("map", {}).get("attribution", "")})
        if len(redirects) > 2000:
            raise PortfolioError("Redirect rules exceed Pages' static-rule budget; move additional legacy paths to Bulk Redirects before deployment")
        # Two placeholders cover every slide, including future appearances, without
        # accumulating thousands of per-slide rules or consuming new rule slots.
        redirects.extend(["/:id/slides/:slide /:id/slides/#:slide 301", "/:id/slides/:slide/ /:id/slides/#:slide 301"])
        (staging / "static/_redirects").write_text("\n".join(redirects) + "\n")
        return staging

    def build(self, local=False, base_url=None):
        (self.root / ".portfolio").mkdir(exist_ok=True)
        with (self.root / ".portfolio/build.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return self._build(local, base_url)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _build(self, local=False, base_url=None):
        staging = self.prepare_site(local=local)
        next_output = self.root / ".portfolio/output-next"
        command = ["zola", "--root", staging, "build", "--output-dir", next_output, "--force"]
        if local:
            command.append("--drafts")
        if base_url:
            command.extend(["--base-url", base_url])
        run(command)
        validate_built_links(next_output, base_url or tomllib.loads((self.root / "zola.toml").read_text())["base_url"])
        if not local:
            for path in next_output.rglob("*"):
                if path.is_file() and path.stat().st_size > PAGE_LIMIT:
                    raise PortfolioError(f"Built file exceeds Cloudflare Pages limit: {path.relative_to(next_output)}")
        destination = self.root / ".portfolio/preview" if local else self.root / "public"
        previous = self.root / ".portfolio/output-previous"
        if previous.exists():
            shutil.rmtree(previous)
        if destination.exists():
            destination.rename(previous)
        next_output.rename(destination)
        if previous.exists():
            shutil.rmtree(previous)
        print("Built " + str(destination))
        return destination

    def preview(self, port):
        url = f"http://127.0.0.1:{port}"
        self.build(local=True, base_url=url)
        version = [time.time_ns()]
        root = self.root

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(root / ".portfolio/preview"), **kwargs)

            def do_GET(self):
                if self.path == "/__portfolio_version":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(str(version[0]).encode())
                else:
                    super().do_GET()

            def log_message(self, *args):
                pass

        def signature():
            return tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for directory in ("content", "data", "templates", "static", "themes", "notes")
                         for p in sorted((root / directory).rglob("*")) if p.is_file()) + tuple((name, (root / name).stat().st_mtime_ns) for name in ("zola.toml", "portfolio.toml"))

        stop = threading.Event()

        def watch():
            previous = signature()
            while not stop.wait(1):
                current = signature()
                if current == previous:
                    continue
                previous = current
                try:
                    self.settings = tomllib.loads((root / "portfolio.toml").read_text())
                    self.build(local=True, base_url=url)
                    version[0] = time.time_ns()
                except Exception as error:
                    print(f"Preview rebuild failed; keeping previous output: {error}", file=sys.stderr)

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=watch, daemon=True).start()
        print(f"Local: {url} (drafts included; edits rebuild and reload automatically)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            server.server_close()


def validate_url(url, allow_local=False):
    if allow_local and url.startswith("/") and not url.startswith("//"):
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise PortfolioError(f"Expected an HTTP(S) URL: {url!r}")


def validate_built_links(output, base_url):
    """Check real generated href/src destinations without fetching external websites."""
    from urllib.parse import urljoin, unquote
    host = urlparse(base_url).netloc
    failures = []

    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            for key in ("href", "src"):
                if attrs.get(key):
                    self.links.append(attrs[key])

    for path in output.rglob("*.html"):
        links = Links()
        links.feed(path.read_text())
        page_url = base_url.rstrip("/") + "/" + str(path.relative_to(output))
        for link in links.links:
            parsed = urlparse(urljoin(page_url, link))
            if parsed.scheme not in ("http", "https") or parsed.netloc != host:
                continue
            relative = unquote(parsed.path).lstrip("/")
            target = output / relative
            if not target.is_file() and not (target / "index.html").is_file():
                failures.append(f"{path.relative_to(output)} → {link}")
    if failures:
        raise PortfolioError("Broken internal links:\n" + "\n".join(failures[:20]))


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Portfolio checkout (defaults to this project)")
    commands = cli.add_subparsers(dest="command")
    commands.add_parser("menu", help="Open the interactive authoring menu")
    new = commands.add_parser("new", help="Create an editable appearance, optionally from a previous one")
    for name in ("title", "event", "date", "location", "id", "talk", "event-url"):
        new.add_argument("--" + name)
    new.add_argument("--timezone", help="Optional IANA timezone metadata; dates do not require one")
    new.add_argument("--from", dest="from_appearance")
    new.add_argument("--reuse-slides", action="store_true", help="Explicitly reuse the previous deck with --from; repeats otherwise start without slides")
    new.add_argument("--publish", action="store_true", help="Include in production immediately; otherwise start as a draft")
    commands.add_parser("repeat", help="Choose a previous talk and create another event appearance")
    edit = commands.add_parser("edit", help="Choose a talk and open its Markdown file")
    edit.add_argument("appearance", nargs="?", help="Optional Markdown path or ID; otherwise choose from a list")
    slides = commands.add_parser("slides", help="Process all PDF pages locally and attach an immutable deck version")
    slides.add_argument("appearance", nargs="?", help="Optional Markdown path or ID; otherwise choose from a list")
    slides.add_argument("pdf", nargs="?", type=Path, help="Optional PDF path; otherwise prompt")
    recording = commands.add_parser("recording", help="Add or replace a recording URL")
    recording.add_argument("appearance", nargs="?")
    recording.add_argument("url", nargs="?")
    notes = commands.add_parser("notes", help="Edit slide titles/transcriptions in TOML, preserving immutable PDF versions")
    notes.add_argument("appearance", nargs="?")
    publish = commands.add_parser("publish", help="Include an appearance in production builds (does not deploy)")
    publish.add_argument("appearance", nargs="?")
    place = commands.add_parser("place", help="Save a new location from an OpenStreetMap link; no geocoding service required")
    place.add_argument("name")
    place.add_argument("--map-url", required=True)
    check = commands.add_parser("check", help="Validate editable content, deck references, and immutable assets")
    check.add_argument("--production", action="store_true")
    build = commands.add_parser("build", help="Build the production site into public/ (no PDF processing or network access)")
    build.add_argument("--base-url", help="Deployment URL override; defaults to PORTFOLIO_BASE_URL or zola.toml")
    preview = commands.add_parser("preview", help="Preview drafts with automatic rebuild and reload")
    preview.add_argument("--port", type=int, default=1112)
    commands.add_parser("doctor", help="Check the required local tools")
    assets = commands.add_parser("assets", help="Commit and push assets with Git, or clone the pinned checkout")
    actions = assets.add_subparsers(dest="asset_action", required=True)
    upload = actions.add_parser("publish", help="Commit and push public assets, then record their Git revision")
    fetch = actions.add_parser("fetch", help="Clone and verify the assets commit required by this portfolio")
    return cli


def new_from_menu(project, repeat=False):
    args = parser().parse_args(["new"])
    if repeat:
        args.from_appearance = project.choose_appearance()
    ident = project.new(args)
    previous = project.appearance(args.from_appearance)[1] if repeat else None
    has_previous_deck = bool(previous and previous["extra"].get("deck"))
    question = "PDF path (optional; Enter leaves this talk without slides)"
    if has_previous_deck:
        question = f"PDF path (Enter for no slides; type 'reuse' to use {previous['extra']['event']}'s slides)"
    source = prompt(question, required=False)
    if source.casefold() == "reuse" and has_previous_deck:
        path, metadata, body = project.appearance(ident)
        metadata["extra"]["deck"] = previous["extra"]["deck"]
        write_page(path, metadata, body)
        print("Reusing slides from " + previous["extra"]["event"] + ".")
    elif source:
        project.attach_pdf(ident, pdf_path(source))
    project.edit(ident)


def interactive_menu(project):
    if not sys.stdin.isatty():
        raise PortfolioError("The interactive menu needs a terminal")
    while True:
        print("\nSpeaking portfolio\n"
              "  1. New talk\n"
              "  2. Repeat a previous talk at another event\n"
              "  3. Edit a talk's Markdown\n"
              "  4. Add or replace slides\n"
              "  5. Add a recording\n"
              "  6. Edit slide notes\n"
              "  7. Preview the site\n"
              "  8. Mark a draft ready for publication\n"
              "  9. Check the portfolio\n"
              "  10. Commit and push public assets\n"
              "  q. Quit")
        choice = input("Choose an action: ").strip().casefold()
        try:
            if choice in ("q", "quit", ""):
                return
            if choice in ("1", "2"):
                new_from_menu(project, repeat=choice == "2")
            elif choice == "3":
                project.edit(project.choose_appearance())
            elif choice == "4":
                ident = project.choose_appearance()
                project.attach_pdf(ident, pdf_path(prompt("PDF path (you can drag the file here)")))
            elif choice == "5":
                ident = project.choose_appearance()
                project.recording(ident, prompt("Recording URL"))
            elif choice == "6":
                project.notes(project.choose_appearance())
            elif choice == "7":
                project.preview(1112)
            elif choice == "8":
                project.publish(project.choose_appearance(drafts_only=True))
            elif choice == "9":
                project.check(report=True)
            elif choice == "10":
                project.asset_repository.publish()
            else:
                print("Choose a number from the menu, or q to quit.")
        except UserCancelled as error:
            if str(error):
                print(str(error))
            continue
        except (PortfolioError, ValueError, OSError, subprocess.CalledProcessError) as error:
            print("Error: " + str(error), file=sys.stderr)


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        project = Portfolio(args.root)
        (project.root / ".portfolio").mkdir(exist_ok=True)
        if args.command is None and not sys.stdin.isatty():
            parser().print_help()
        elif args.command in (None, "menu"):
            interactive_menu(project)
        elif args.command == "new":
            project.new(args)
        elif args.command == "repeat":
            new_from_menu(project, repeat=True)
        elif args.command == "edit":
            project.edit(project.choose_appearance(args.appearance))
        elif args.command == "slides":
            # A PDF can be supplied on its own; the talk is then chosen by name.
            if args.appearance and args.pdf is None and str(args.appearance).lower().endswith(".pdf"):
                args.pdf, args.appearance = Path(args.appearance), None
            ident = project.choose_appearance(args.appearance)
            source = args.pdf if args.pdf is not None else pdf_path(prompt("PDF path (you can drag the file here)"))
            project.attach_pdf(ident, source)
        elif args.command == "recording":
            if args.appearance and args.url is None and args.appearance.startswith(("https://", "http://")):
                args.url, args.appearance = args.appearance, None
            ident = project.choose_appearance(args.appearance)
            project.recording(ident, args.url or prompt("Recording URL"))
        elif args.command == "notes":
            project.notes(project.choose_appearance(args.appearance))
        elif args.command == "publish":
            project.publish(project.choose_appearance(args.appearance, drafts_only=True))
        elif args.command == "place":
            project.place(args.name, args.map_url)
        elif args.command == "check":
            project.check(production=args.production, report=True)
        elif args.command == "build":
            project.build(base_url=args.base_url or os.environ.get("PORTFOLIO_BASE_URL") or None)
        elif args.command == "assets":
            if args.asset_action == "publish":
                project.asset_repository.publish()
            else:
                project.asset_repository.fetch()
        elif args.command == "preview":
            project.preview(args.port)
        elif args.command == "doctor":
            missing = []
            for tool in ("zola", "pdfinfo", "pdftoppm"):
                found = shutil.which(tool)
                print(f"{tool}: {found or 'missing'}")
                if not found:
                    missing.append(tool)
            print("Install Zola and Poppler (macOS: brew install zola poppler).")
            if missing:
                raise PortfolioError("Missing tools: " + ", ".join(missing))
    except (UserCancelled, KeyboardInterrupt, EOFError) as error:
        print("\n" + (str(error) if isinstance(error, UserCancelled) and str(error) else "Cancelled."))
        return 0
    except (PortfolioError, tomlkit.exceptions.ParseError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1
    return 0
