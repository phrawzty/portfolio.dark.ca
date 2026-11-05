#!/usr/bin/env python3
"""Recover public deck originals/images/text; optionally reconstruct and validate PDFs.

Use the bundled Python runtime (reportlab, pypdf, Pillow, Poppler).
  python3 scripts/recover_notist.py download
  python3 scripts/recover_notist.py build
  python3 scripts/recover_notist.py validate  # recheck existing PDFs, without authoring
All network access is read-only. Downloads are streamed, checked and resumable.
"""
import concurrent.futures
import csv
import hashlib
import html
import json
import io
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageChops, ImageOps, ImageStat, ImageDraw
from audit_notist import Document, clean

ROOT = Path(__file__).resolve().parents[2] / "assets.dark.ca/preservation"
AUDIT = ROOT / "audit/2026-11-05"
ARCHIVE = ROOT / "archive"
PDF_OUT = ROOT / "output/pdf"
TMP = ROOT / "tmp/pdfs"
MANIFEST = ARCHIVE / "downloads.json"
LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
LAST_REQUEST = 0
TALKS = json.loads((AUDIT / "presentations.json").read_text())


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def slides(talk):
    return [slide for deck in talk["detail"].get("attributes", {}).get("slidedeck", {}).get("data", []) for slide in deck.get("slides", [])]


def parallel(function, items):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(function, items))


def download():
    global LAST_REQUEST
    ARCHIVE.mkdir(exist_ok=True)
    existing = {x["url"]: x for x in json.loads(MANIFEST.read_text())} if MANIFEST.exists() else {}
    jobs = {}
    for talk in TALKS:
        for url in talk["pdf_urls"]:
            jobs[url] = ("original_pdf", ARCHIVE / "originals" / Path(urlparse(url).path).name)
        for slide in slides(talk):
            if slide.get("image"):
                url = slide["image"]
                jobs[url] = ("slide_image", ARCHIVE / "media" / urlparse(url).path.lstrip("/"))
        if slides(talk):
            jobs[f"https://speaking.dark.ca/{talk['id']}/slides"] = ("all_slides_html", ARCHIVE / "presentations" / talk["id"] / "slides.html")
    with (AUDIT / "asset-references.csv").open() as stream:
        for asset in csv.DictReader(stream):
            url = asset["url"]
            if urlparse(url).hostname == "on.notist.cloud" and urlparse(url).path.startswith(("/headshots/", "/profile/")):
                jobs[url] = ("speaker_image", ARCHIVE / "media" / urlparse(url).path.lstrip("/"))
    results = dict(existing)
    done = 0

    def get(job):
        nonlocal done
        global LAST_REQUEST
        url, (kind, path) = job
        old = existing.get(url, {})
        if path.is_file() and old.get("sha256") == digest(path):
            return old
        receipt = {"url": url, "kind": kind, "path": str(path.relative_to(ROOT)), "downloaded_at": datetime.now(timezone.utc).isoformat()}
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".part")
        for attempt in range(3):
            try:
                with RATE_LOCK:
                    time.sleep(max(0, LAST_REQUEST + 1 / 6 - time.monotonic()))
                    LAST_REQUEST = time.monotonic()
                request = Request(url, headers={"User-Agent": "speaking.dark.ca-public-preservation/1.0", "Accept-Encoding": "identity"})
                checksum = hashlib.sha256()
                size = 0
                with urlopen(request, timeout=60) as response, partial.open("wb") as output:
                    while block := response.read(1024 * 1024):
                        output.write(block)
                        checksum.update(block)
                        size += len(block)
                    expected = response.headers.get("Content-Length")
                    if expected and int(expected) != size:
                        raise ValueError(f"Incomplete body: expected {expected}, received {size}")
                    receipt.update(status=response.status, final_url=response.url, content_type=response.headers.get("Content-Type"), bytes=size, sha256=checksum.hexdigest(), content_length=expected)
                if kind == "original_pdf":
                    with partial.open("rb") as pdf_stream:
                        if not pdf_stream.read(1024).lstrip().startswith(b"%PDF-"):
                            raise ValueError("Downloaded body is not a PDF")
                if kind in ("slide_image", "speaker_image"):
                    with Image.open(partial) as image:
                        receipt.update(width=image.width, height=image.height, image_format=image.format)
                        image.verify()
                if kind == "all_slides_html" and "slide-image" not in partial.read_text():
                    raise ValueError("All-slides page does not contain slides")
                partial.replace(path)
                receipt.pop("error", None)
                break
            except Exception as error:
                receipt["error"] = str(error)
                partial.unlink(missing_ok=True)
                if attempt < 2:
                    time.sleep(attempt + 1)
        with LOCK:
            results[url] = receipt
            done += 1
            if done % 25 == 0 or "error" in receipt:
                write_json(MANIFEST, sorted(results.values(), key=lambda r: r["url"]))
                print(f"Downloaded {done}/{len(jobs)}; {kind}: {path.name}" + (" ERROR " + receipt["error"] if "error" in receipt else ""), flush=True)
        return receipt

    parallel(get, jobs.items())
    write_json(MANIFEST, sorted(results.values(), key=lambda r: r["url"]))
    discrepancies = []
    for talk in TALKS:
        directory = ARCHIVE / "presentations" / talk["id"]
        directory.mkdir(parents=True, exist_ok=True)
        records = []
        for i, slide in enumerate(slides(talk), 1):
            source = slide.get("desc", {}).get("html") or ""
            description = clean(Document(source).root.text())
            text = clean((slide.get("title") or "") + " " + description)
            records.append({**slide, "number": i, "text": text, "description_text": description, "local_image": results.get(slide.get("image"), {}).get("path")})
        all_slides = directory / "slides.html"
        if records and all_slides.exists():
            nodes = list(Document(all_slides.read_text()).root.walk())
            image_urls = [n.attrs.get("src") for n in nodes if n.tag == "img" and n.hasclass("slide-image")]
            expected = [s.get("image") for s in slides(talk)]
            if image_urls != expected:
                discrepancies.append({"id": talk["id"], "kind": "all_slides_image_order", "expected": expected, "observed": image_urls})
            descriptions = [n for n in nodes if n.attrs.get("id", "").startswith("slide") and n.attrs.get("id", "").endswith("-desc")]
            for i, desc in enumerate(descriptions):
                if i < len(records):
                    records[i]["all_slides_text"] = clean(desc.text())
                    if records[i]["text"] != clean(desc.text()):
                        discrepancies.append({"id": talk["id"], "kind": "transcription_difference", "slide": i + 1})
        write_json(directory / "slides.json", records)
        (directory / "transcript.txt").write_text(talk["title"].strip() + "\n\n" + "\n\n".join(f"Slide {s['number']} ({s['id']})\n{s['text']}" for s in records) + "\n")
        body = "\n".join(f'<section id="{html.escape(s["id"])}"><h2>Slide {s["number"]}</h2>' + (f'<h3>{html.escape(s["title"])}</h3>' if s.get("title") else '') + (s.get("desc", {}).get("html") or "<p>No transcription available.</p>") + '</section>' for s in records)
        (directory / "transcript.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>' + html.escape(talk["title"]) + '</title><body><h1>' + html.escape(talk["title"]) + '</h1>' + body + '</body></html>\n')
    failures = [r for r in results.values() if "error" in r]
    report = {"download_count": len(jobs), "failures": failures, "all_slides_discrepancies": discrepancies,
              "bytes": sum(r.get("bytes", 0) for r in results.values()), "original_pdf_count": sum(r["kind"] == "original_pdf" and "error" not in r for r in results.values()),
              "slide_image_count": sum(r["kind"] == "slide_image" and "error" not in r for r in results.values())}
    write_json(ARCHIVE / "download-summary.json", report)
    print(json.dumps(report, indent=2), flush=True)
    if failures or discrepancies:
        raise SystemExit("Recovery requires review; see archive/download-summary.json")


def build():
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    from pypdf import PdfReader

    downloads = {r["url"]: r for r in json.loads(MANIFEST.read_text())}
    PDF_OUT.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    validation_only = sys.argv[1] == "validate"
    reconstructed = json.loads((ARCHIVE / "reconstructed-pdfs.json").read_text()) if validation_only else []
    for talk in ([] if validation_only else TALKS):
        if talk["pdf_state"] != "original_pdf_link_not_exposed":
            continue
        records = slides(talk)
        path = PDF_OUT / f"{talk['id']}-{talk['detail']['attributes']['slug']}-reconstructed.pdf"
        pdf = canvas.Canvas(str(path), pageCompression=1)
        pdf.setTitle(talk["title"].strip() + " [Reconstructed from Notist slide images]")
        pdf.setAuthor('Daniel "phrawzty" Maher')
        pdf.setSubject("Reconstructed from archived slide images; not the original uploaded PDF. Source: " + talk["url"])
        for slide in records:
            receipt = downloads[slide["image"]]
            if "error" in receipt:
                raise ValueError("Cannot reconstruct with a missing slide: " + slide["image"])
            image_path = ROOT / receipt["path"]
            with Image.open(image_path) as image:
                width, height = image.size
            # 1600 px becomes 960 pt: keep a uniform scale without cropping.
            scale = 960 / width
            pdf.setPageSize((width * scale, height * scale))
            pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=width * scale, height=height * scale, mask="auto")
            pdf.showPage()
        pdf.save()
        reconstructed.append({"id": talk["id"], "path": str(path.relative_to(ROOT)), "pages": len(records), "sha256": digest(path), "kind": "reconstructed", "source": talk["url"]})
    write_json(ARCHIVE / "reconstructed-pdfs.json", reconstructed)
    print(f"{'Rechecking' if validation_only else 'Created'} {len(reconstructed)} labelled reconstructed PDFs", flush=True)
    original_jobs = [(r, None) for r in downloads.values() if r["kind"] == "original_pdf" and "error" not in r]
    reconstruction_jobs = [(r, next(t for t in TALKS if t["id"] == r["id"])) for r in reconstructed]

    previous = {r["path"]: r for r in json.loads((ARCHIVE / "pdf-validation.json").read_text())} if (ARCHIVE / "pdf-validation.json").exists() else {}

    def verify_embedded(reader, talk):
        errors, jpeg_pages = [], []
        if len(reader.pages) != len(slides(talk)):
            raise ValueError("Reconstructed page count differs from archived slides")
        for number, (page, slide) in enumerate(zip(reader.pages, slides(talk)), 1):
            source = ROOT / downloads[slide["image"]]["path"]
            objects = [v.get_object() for v in page["/Resources"]["/XObject"].values() if v.get_object().get("/Subtype") == "/Image"]
            if len(objects) != 1:
                raise ValueError("Expected one image per PDF page")
            obj = objects[0]
            filters = obj.get("/Filter", [])
            filters = filters if isinstance(filters, list) else [filters]
            with Image.open(source) as expected:
                if (obj["/Width"], obj["/Height"]) != expected.size:
                    raise ValueError("Embedded dimensions differ from source")
                if abs(float(page.mediabox.width) / float(page.mediabox.height) - expected.width / expected.height) > 0.00001:
                    raise ValueError("PDF page aspect ratio differs from source")
                if "/DCTDecode" in filters:
                    # pypdf page.images re-encodes JPEGs when exporting them. Check
                    # the original compressed stream instead: these bytes must match.
                    if hashlib.sha256(obj.get_data()).hexdigest() != digest(source):
                        raise ValueError("Embedded JPEG differs from archived source bytes")
                    jpeg_pages.append(number)
                    errors.append(0.0)
                else:
                    actual = list(page.images)[0].image.convert("RGB")
                    error = sum(ImageStat.Stat(ImageChops.difference(actual, expected.convert("RGB"))).mean) / 3
                    if error != 0:
                        raise ValueError("Lossless embedded pixels differ from source")
                    errors.append(error)
        return {"embedded_image_mean_absolute_errors": errors, "jpeg_pages_with_identical_source_bytes": jpeg_pages,
                "embedded_verification": "JPEG compressed bytes match exactly; lossless image pixels match exactly; all dimensions and page aspect ratios match."}

    def validate(job):
        record, talk = job
        path = ROOT / record["path"]
        key = path.stem
        directory = TMP / key
        directory.mkdir(exist_ok=True)
        result = {"path": record["path"], "sha256": digest(path), "kind": "reconstructed" if talk else "original", "issues": []}
        old = previous.get(record["path"], {})
        if not talk and old.get("sha256") == result["sha256"] and old.get("rendered_pages") and not old.get("issues"):
            return old
        if talk and old.get("sha256") == result["sha256"] and old.get("renderer_exit_code") == 0 and old.get("rendered_pages"):
            result = dict(old)
            result["issues"] = [issue for issue in old["issues"] if issue not in ("Embedded image pixels differ from archived source", "Image comparison exceeds review threshold")]
            try:
                result.update(verify_embedded(PdfReader(path, strict=True), talk))
            except Exception as error:
                result["issues"].append(str(error))
            print(f"Verified source images in {path.name}; reused successful renders for unchanged PDF", flush=True)
            return result
        try:
            reader = PdfReader(path, strict=True)
            result["pages"] = len(reader.pages)
            result["page_sizes"] = [[float(p.mediabox.width), float(p.mediabox.height)] for p in reader.pages]
            for page in reader.pages:
                if float(page.mediabox.width) <= 0 or float(page.mediabox.height) <= 0:
                    raise ValueError("Invalid page geometry")
                page.get_contents().get_data() if page.get_contents() is not None else None
            rendered = subprocess.run(["pdftoppm", "-scale-to", "600", "-png", str(path), str(directory / "page")], capture_output=True, text=True)
            result["renderer_exit_code"] = rendered.returncode
            if rendered.stderr:
                result["renderer_messages"] = rendered.stderr[-12000:]
            if rendered.returncode:
                raise ValueError("Poppler failed to render every page")
            pages = sorted(directory.glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
            if len(pages) != result["pages"]:
                raise ValueError("Rendered page count does not match parsed PDF")
            result["rendered_pages"] = len(pages)
            for page in pages:
                with Image.open(page) as image:
                    image.load()
            if talk:
                if len(pages) != len(slides(talk)):
                    raise ValueError("Reconstructed PDF page count differs from displayed deck")
                errors = []
                embedded_errors = []
                for page_number, (rendered_page, slide) in enumerate(zip(pages, slides(talk))):
                    original = ROOT / downloads[slide["image"]]["path"]
                    embedded = list(reader.pages[page_number].images)
                    if len(embedded) != 1:
                        raise ValueError("Expected one embedded source image per reconstructed page")
                    with Image.open(original) as expected:
                        actual = embedded[0].image.convert("RGB")
                        if actual.size != expected.size:
                            raise ValueError("Embedded image dimensions differ from archived source")
                        embedded_error = sum(ImageStat.Stat(ImageChops.difference(actual, expected.convert("RGB"))).mean) / 3
                        embedded_errors.append(round(embedded_error, 6))
                        geometry = result["page_sizes"][page_number]
                        if abs(geometry[0] / geometry[1] - expected.width / expected.height) > 0.00001:
                            raise ValueError("Reconstructed page aspect ratio differs from source image")
                    with Image.open(rendered_page) as actual, Image.open(original) as expected:
                        expected = expected.convert("RGB").resize(actual.size, Image.Resampling.LANCZOS)
                        error = sum(ImageStat.Stat(ImageChops.difference(actual.convert("RGB"), expected)).mean) / 3
                        errors.append(round(error, 3))
                result["page_image_mean_absolute_errors"] = errors
                result["embedded_image_mean_absolute_errors"] = embedded_errors
                result["render_comparison_note"] = "Rendered-image errors are diagnostic: Poppler and Pillow use different sampling. Source image pixels and page geometry are checked separately."
                result.update(verify_embedded(reader, talk))
            # Contact sheets cover every page of every original and reconstruction.
            sheet_paths = []
            for start in range(0, len(pages), 60):
                batch = pages[start:start + 60]
                sheet = Image.new("RGB", (1200, ((len(batch) + 4) // 5) * 160), "#dddddd")
                draw = ImageDraw.Draw(sheet)
                for i, page in enumerate(batch):
                    with Image.open(page) as image:
                        thumbnail = ImageOps.contain(image.convert("RGB"), (232, 136))
                        x, y = (i % 5) * 240, (i // 5) * 160
                        sheet.paste(thumbnail, (x + (240 - thumbnail.width) // 2, y))
                        draw.text((x + 5, y + 140), str(start + i + 1), fill="black")
                output = directory / f"contact-{start // 60 + 1}.jpg"
                sheet.save(output, quality=85)
                sheet_paths.append(str(output.relative_to(ROOT)))
            result["contact_sheets"] = sheet_paths
            # Keep contact sheets for review; full-size validation renders are disposable.
            for page in pages:
                page.unlink()
        except Exception as error:
            result["issues"].append(str(error))
        print(f"Validated {path.name}: {result.get('rendered_pages', 0)} pages; {len(result['issues'])} issues", flush=True)
        return result

    validations = parallel(validate, original_jobs + reconstruction_jobs)
    write_json(ARCHIVE / "pdf-validation.json", validations)
    pdf_by_url = {r["url"]: r for r in downloads.values() if r["kind"] == "original_pdf"}
    reconstruction_by_id = {r["id"]: r for r in reconstructed}
    coverage = []
    for talk in TALKS:
        original = [pdf_by_url[u]["path"] for u in talk["pdf_urls"]]
        rebuilt = reconstruction_by_id.get(talk["id"])
        entry = {"id": talk["id"], "title": talk["title"], "displayed_slides": len(slides(talk)), "original_pdfs": original,
                 "reconstructed_pdf": rebuilt["path"] if rebuilt else None, "status": "original_recovered" if original else "reconstructed" if rebuilt else talk["pdf_state"]}
        original_counts = [v.get("pages") for v in validations if v["path"] in original]
        entry["original_page_counts"] = original_counts
        entry["original_displayed_count_differs"] = bool(original_counts and any(c != entry["displayed_slides"] for c in original_counts))
        coverage.append(entry)
    write_json(ARCHIVE / "presentation-coverage.json", coverage)
    source_warnings = []
    logger = logging.getLogger("pypdf")
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    logger.addHandler(handler)
    try:
        for record, _ in original_jobs:
            captured.seek(0)
            captured.truncate(0)
            PdfReader(ROOT / record["path"], strict=True)
            parser_warning = captured.getvalue().strip()
            renderer_warning = next((v.get("renderer_messages", "") for v in validations if v["path"] == record["path"]), "")
            if parser_warning or renderer_warning:
                source_warnings.append({"path": record["path"], "parser_warnings": parser_warning, "renderer_warnings": renderer_warning,
                    "presentation_ids": [t["id"] for t in TALKS if record["url"] in t["pdf_urls"]],
                    "note": "Pre-existing source syntax warnings; original bytes unchanged and every page rendered successfully."})
    finally:
        logger.removeHandler(handler)
    write_json(ARCHIVE / "pdf-source-warnings.json", source_warnings)
    report = {"original_pdfs": len(original_jobs), "reconstructed_pdfs": len(reconstructed), "parsed_and_rendered_pages": sum(v.get("rendered_pages", 0) for v in validations),
              "validation_issues": [v for v in validations if v["issues"]],
              "originals_with_source_syntax_warnings": len(source_warnings),
              "original_displayed_count_differences": [c for c in coverage if c["original_displayed_count_differs"]]}
    write_json(ARCHIVE / "pdf-summary.json", report)
    readme = ["PUBLIC PORTFOLIO RECOVERY", "",
        f"{len(original_jobs)} distinct original PDFs recovered; mapped to their presentation pages in presentation-coverage.json.",
        f"{len(reconstructed)} reconstructed PDFs created under output/pdf/ for multi-slide decks with no exposed original.",
        f"{report['parsed_and_rendered_pages']} PDF pages parsed and rendered locally. Validation issues: {len(report['validation_issues'])}.",
        "", "ORIGINALS AND RECONSTRUCTIONS", "",
        "originals/: byte-preserved original PDF downloads, with complete-response lengths and SHA-256 checksums in downloads.json.",
        "Reconstructed PDFs carry '-reconstructed' in their filenames and reconstruction provenance in their PDF metadata.",
        "They preserve displayed image order and aspect ratios; they do not recover vector text, original PDF hyperlinks, or unavailable notes.",
        "Four single-image presentations are archived as images, not presented as recovered original decks.",
        "Ten video-only and two deckless entries have no observed deck to reconstruct.",
        "", "SLIDES AND TRANSCRIPTS", "",
        "media/: original full-size slide and speaker images, stored without conversion.",
        "presentations/<id>/slides.html: captured public all-slides page where one exists.",
        "presentations/<id>/slides.json: ordered slide records, titles, descriptions and local image paths.",
        "presentations/<id>/transcript.html and transcript.txt: available text, including custom slide titles.",
        "Unavailable text has not been invented or replaced with OCR. Image-only slides may have no transcription.",
        "Descriptions, events, resources, feedback and resolved recording links remain preserved in audit/2026-11-05/.",
        "", "VALIDATION", "",
        "pdf-validation.json: page counts, page geometry, Poppler render results and reconstruction image comparisons.",
        "Every PDF page was parsed and rendered; reconstructed pages were compared to their source images.",
        f"{len(source_warnings)} original files emit pre-existing source syntax warnings; see pdf-source-warnings.json. Their bytes are preserved unchanged and every page renders.",
        "Contact sheets are kept under tmp/pdfs/ for visual review; individual validation PNGs are disposable.",
        "presentation-coverage.json: records each presentation independently, including variants sharing a PDF.",
        "Original/displayed page-count differences (not automatically corruption):"]
    for item in report["original_displayed_count_differences"]:
        readme.append(f"- {item['id']}: original {item['original_page_counts']} pages; displayed {item['displayed_slides']} slides.")
    readme.extend(["", "LIMITATIONS", "",
        "Recording provider URLs are preserved; third-party video bodies and linked social-media images are not downloaded.",
        "External resource destinations are inventoried, not exhaustively mirrored.",
        "No account settings, DNS, Git remotes or hosting configuration have been changed.",
        "Four original PDFs exceed Cloudflare Pages' 25 MiB asset limit; their downloads are intended for GitHub Releases.",
        "This is a local preservation copy; keep an independent backup before retiring the source account.",
        "", "RECONSTRUCTED DECKS", ""])
    readme.extend(r["id"] + ": " + r["path"] for r in reconstructed)
    (ARCHIVE / "README.txt").write_text("\n".join(readme) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    if report["validation_issues"]:
        raise SystemExit("PDF validation requires review")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("download", "build", "validate"):
        raise SystemExit(__doc__)
    download() if sys.argv[1] == "download" else build()
