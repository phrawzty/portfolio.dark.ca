#!/usr/bin/env python3
"""One-time import of the verified public recovery into the normal authoring model.

Run with `uv run python scripts/import_notist.py`. Never needed to add future talks.
Use --resume after an interrupted import; existing editable pages are never overwritten.
"""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime
from zoneinfo import ZoneInfo

import tomlkit
from PIL import Image
from portfolio.cli import Portfolio, slug, sha256, json_file, write_page
from audit_notist import Document, Node

ROOT = Path(__file__).resolve().parents[1]
PRESERVATION = ROOT.parent / "assets.dark.ca/preservation"
AUDIT = PRESERVATION / "audit/2026-11-05"


def recording_url(url):
    parsed = urlparse(url)
    if parsed.hostname in ("www.youtube.com", "www.youtube-nocookie.com"):
        ident = parsed.path.rsplit("/", 1)[-1]
        query = {"v": ident}
        start = parse_qs(parsed.query).get("start")
        if start:
            query["t"] = start[0] + "s"
        return "https://www.youtube.com/watch?" + urlencode(query)
    if parsed.hostname == "player.vimeo.com":
        return "https://vimeo.com/" + parsed.path.rsplit("/", 1)[-1] + ("?" + parsed.query if parsed.query else "")
    return url


def node_html(node):
    if isinstance(node, str):
        return html.escape(node)
    if node.tag in ("script", "style"):
        return ""
    attrs = "".join(" " + key + ('="' + html.escape(value, quote=True) + '"' if value is not None else "") for key, value in node.attrs.items())
    inside = "".join(node_html(child) for child in node.children)
    return "<" + node.tag + attrs + ">" + inside + ("" if node.tag in Document.VOID else "</" + node.tag + ">")


def register_file(source, relative, files):
    target = Portfolio(ROOT).asset_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    checksum = sha256(source)
    if target.exists():
        if sha256(target) != checksum:
            raise ValueError("Existing immutable asset differs: " + str(target))
    else:
        shutil.copy2(source, target)
    files.append({"path": relative, "sha256": checksum, "bytes": source.stat().st_size})


def without_nulls(value):
    if isinstance(value, dict):
        return {k: without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_nulls(v) for v in value if v is not None]
    return value


def main():
    project = Portfolio(ROOT)
    if project.appearances() and "--resume" not in sys.argv:
        raise SystemExit("Appearances already exist. Use --resume to skip existing pages without overwriting edits.")
    presentations = json.loads((AUDIT / "presentations.json").read_text())
    downloads = {x["url"]: x for x in json.loads((PRESERVATION / "archive/downloads.json").read_text())}
    coverage = {x["id"]: x for x in json.loads((PRESERVATION / "archive/presentation-coverage.json").read_text())}
    imported = []
    for source in presentations:
        ident = source["id"]
        destination = ROOT / "content/appearances" / (ident + ".md")
        if destination.exists():
            continue
        talk_id = slug(source["title"])
        detail = source["detail"]["attributes"]
        body = (detail.get("blurb", {}).get("html") or "").strip() + "\n"
        talk_path = ROOT / "content/talks" / (talk_id + ".md")
        if not talk_path.exists():
            talk_meta = tomlkit.document()
            talk_meta.update(title=source["title"].strip(), template="talk.html", draft=False)
            write_page(talk_path, talk_meta, body)
        slides = json.loads((PRESERVATION / "archive/presentations" / ident / "slides.json").read_text())
        deck_id = ""
        if slides:
            originals = coverage[ident]["original_pdfs"]
            reconstructed = coverage[ident]["reconstructed_pdf"]
            pdf_source = PRESERVATION / originals[0] if originals else PRESERVATION / reconstructed if reconstructed else None
            state = {"pdf_sha256": sha256(pdf_source) if pdf_source else None,
                     "slides": [{"sha256": downloads[s["image"]]["sha256"], "id": s["id"], "title": s.get("title"), "text": s["text"]} for s in slides]}
            deck_id = hashlib.sha256(json.dumps(state, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            prefix = "decks/" + deck_id
            files, deck_slides = [], []
            for slide in slides:
                receipt = downloads[slide["image"]]
                image_path = PRESERVATION / receipt["path"]
                relative = prefix + f"/{slide['number']:04d}" + image_path.suffix
                register_file(image_path, relative, files)
                with Image.open(image_path) as image:
                    width, height = image.size
                deck_slides.append({"id": slide["id"].removeprefix("sl_"), "number": slide["number"], "image": relative,
                                    "width": width, "height": height, "text": slide.get("description_text", slide["text"]),
                                    "title": slide.get("title") or "", "original_description_html": slide.get("desc", {}).get("html") or ""})
            pdf_relative = ""
            provenance = "original" if originals else "reconstructed" if reconstructed else "image-only"
            if pdf_source:
                pdf_relative = prefix + ("/reconstructed.pdf" if reconstructed else "/original.pdf")
                register_file(pdf_source, pdf_relative, files)
            deck = {"id": deck_id, "source_sha256": state["pdf_sha256"], "provenance": provenance, "pdf": pdf_relative,
                    "slides": deck_slides, "page_count": len(slides), "files": files,
                    "processor": "notist-preserved-display-v1", "source_url": source["url"]}
            json_file(ROOT / "data/decks" / (deck_id + ".json"), deck)
        event = next(r for r in source["detail"]["relationships"]["data"] if r["type"] == "events")
        event_attrs = event["attributes"]
        meta = tomlkit.document()
        meta.update(title=source["title"].strip(), date=datetime.fromisoformat(source["presented_on"]).replace(tzinfo=ZoneInfo(source["timezone"])),
                    draft=False, path=ident, template="appearance.html")
        aliases = [ident + "/" + detail["slug"]]
        if source["embed_wrappers"]:
            aliases.append("videos/" + ident)
        meta["aliases"] = aliases
        destinations = [u for item in source.get("resolved_embeds", []) for u in item["destinations"]]
        extra = {"id": ident, "talk": talk_id, "event": event_attrs["title"], "event_url": event_attrs.get("url") or "",
                 "location": event_attrs.get("address") or "Virtual", "timezone": source["timezone"], "virtual": not event_attrs.get("latitude"),
                 "deck": deck_id, "recording_url": recording_url(destinations[0]) if destinations else "",
                 "source_url": source["url"], "source_event_id": event["id"], "source_published_on": source["published_on"],
                 "resources": [{"title": r["title"], "url": r["url"], "description": r.get("desc", {}).get("html") or ""} for r in source["resources"]],
                 "feedback": []}
        if event_attrs.get("latitude") is not None and event_attrs.get("longitude") is not None:
            extra.update(latitude=float(event_attrs["latitude"]), longitude=float(event_attrs["longitude"]))
        for feedback in source["feedback"]:
            url = next((u for u in feedback["links"] if "/status/" in u), "")
            author = "@" + urlparse(url).path.strip("/").split("/")[0] if url else "Original post"
            extra["feedback"].append({"text": feedback["text"], "url": url, "author": author, "source_links": feedback["links"]})
        meta["extra"] = tomlkit.item(extra)
        write_page(destination, meta, body)
        imported.append(ident)

    # Independent event records retain descriptions, hashtags and source timestamps.
    events = json.loads((AUDIT / "events.json").read_text())
    for source in events:
        event = source["data"]["data"][0]
        path = ROOT / "data/events" / (event["id"].removeprefix("ev_") + ".toml")
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(tomlkit.dumps(without_nulls({"id": event["id"], **event["attributes"]})))

    site_files, photos = [], []
    for photo in json.loads((AUDIT / "photos.json").read_text()):
        url = next(u for u in photo["urls"] if "/headshots/hs-" in u and not any(size in u for size in ("-large-", "-medium-", "-thumb-")))
        original = PRESERVATION / downloads[url]["path"]
        prefix = "speaker/" + sha256(original)
        relative = prefix + "/headshot.jpg"
        register_file(original, relative, site_files)
        photos.append({"id": photo["id"], "image": relative, "download": relative, "attribution": ""})
    json_file(ROOT / "data/site-assets.json", {"id": "speaker", "files": site_files})
    json_file(ROOT / "data/headshots.json", photos)
    bio_doc = Document((AUDIT / "raw/bio.html").read_text())
    intro = next(n for n in bio_doc.root.walk() if n.hasclass("profile-biog"))
    bios = {}
    for kind in ("short", "full"):
        section = next(n for n in bio_doc.root.walk() if n.attrs.get("id") == kind + "-md")
        textarea = next(n for n in section.walk() if n.tag == "textarea")
        bios[kind] = textarea.text().strip()
    body = "".join(node_html(n) for n in intro.children) + "\n\n## Short biography\n\n" + bios["short"] + "\n\n## Full biography\n\n" + bios["full"] + "\n"
    bio_meta = tomlkit.document()
    bio_meta.update(title="About Dan", template="bio.html", aliases=["photo/" + photo["id"] for photo in photos])
    write_page(ROOT / "content/bio.md", bio_meta, body)
    report = {"imported_ids": [s["id"] for s in presentations], "created_this_run": imported, "appearances": len(project.appearances()), "talks": len(list((ROOT / "content/talks").glob("*.md"))) - 1,
              "resources": sum(len(m["extra"].get("resources", [])) for _, m, _ in project.appearances()),
              "feedback": sum(len(m["extra"].get("feedback", [])) for _, m, _ in project.appearances()),
              "recordings": sum(bool(m["extra"].get("recording_url")) for _, m, _ in project.appearances())}
    json_file(ROOT / "data/migration-report.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
