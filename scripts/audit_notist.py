#!/usr/bin/env python3
"""Read-only public Notist inventory. Downloads metadata, never PDF/media bodies.

Run from the repository root: python3 scripts/audit_notist.py
Saved request evidence is reused; pass --refresh to re-fetch the public site.
Outputs raw evidence, request receipts, and reviewable JSON/CSV inventories.
"""
import concurrent.futures
import csv
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2] / "assets.dark.ca/preservation"
OUT = ROOT / "audit" / "2026-11-05"
BASE = "https://speaking.dark.ca"
RECEIPTS = []
LOCK = threading.Lock()
CACHED = {}
if (OUT / "requests.json").exists() and "--refresh" not in sys.argv:
    CACHED = {(r["url"], r["method"]): r for r in json.loads((OUT / "requests.json").read_text())}


class Node:
    def __init__(self, tag="root", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in ("script", "style"):
            return ""
        return " ".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def hasclass(self, name):
        return name in self.attrs.get("class", "").split()


class Document(HTMLParser):
    VOID = set("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fetch(url, relative=None, method="GET"):
    cached = CACHED.get((url, method))
    if cached and (method == "HEAD" or cached.get("evidence")):
        path = ROOT / cached.get("evidence", "")
        if method == "HEAD" or path.is_file():
            with LOCK:
                RECEIPTS.append(cached)
            return (path.read_text() if method == "GET" else ""), cached
    receipt = {"url": url, "method": method, "checked_at": datetime.now(timezone.utc).isoformat()}
    body = b""
    for attempt in range(3):
        try:
            request = Request(url, method=method, headers={"User-Agent": "speaking.dark.ca-public-preservation-audit/1.0"})
            with urlopen(request, timeout=35) as response:
                body = response.read() if method == "GET" else b""
                receipt.update(status=response.status, final_url=response.url,
                               content_type=response.headers.get("Content-Type"),
                               content_length=response.headers.get("Content-Length"))
            if method == "GET":
                receipt.update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                if relative:
                    path = OUT / "raw" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                    receipt["evidence"] = str(path.relative_to(ROOT))
            break
        except Exception as error:
            receipt["error"] = str(error)
            if attempt < 2:
                time.sleep(attempt + 1)
    if "status" in receipt:
        receipt.pop("error", None)
    with LOCK:
        RECEIPTS.append(receipt)
    return body.decode("utf-8", errors="replace"), receipt


def parse_json(source):
    try:
        return json.loads(source)
    except (ValueError, TypeError):
        return {}


def urls_in(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from urls_in(child)
    elif isinstance(value, list):
        for child in value:
            yield from urls_in(child)
    elif isinstance(value, str):
        yield from re.findall(r"https?://[^\s<>\"']+", value)


def html_urls(doc, base):
    for node in doc.root.walk():
        for key in ("href", "src", "data-flickity-lazyload-src", "poster", "data-src"):
            if node.attrs.get(key):
                yield urljoin(base, node.attrs[key])
        for key in ("srcset", "data-flickity-lazyload-srcset"):
            for part in node.attrs.get(key, "").split(","):
                if part.strip():
                    yield urljoin(base, part.strip().split()[0])


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def parallel(function, items):
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        return list(executor.map(function, items))


def audit_talk(summary):
    ident = summary["id"].removeprefix("pr_")
    attrs = summary.get("attributes", {})
    path = urlparse(summary.get("links", {}).get("self", "")).path
    path = re.sub(r"^/phrawzty/", "/", path)
    page_url = BASE + path
    source, page_receipt = fetch(page_url, f"presentations/{ident}.html")
    exported, json_receipt = fetch(f"{BASE}/{ident}.json", f"presentations/{ident}.json")
    payload = parse_json(exported)
    records = payload.get("data", [])
    record = next((r for r in records if r.get("type") == "presentations"), {})
    detail = record.get("attributes", {})
    doc = Document(source)
    nodes = list(doc.root.walk())
    decks = detail.get("slidedeck", {}).get("data", [])
    slide_nodes = [n for n in nodes if n.hasclass("slide") and n.tag == "figure"]
    slides = [s for deck in decks for s in deck.get("slides", [])]
    urls = sorted(set(html_urls(doc, page_url)) | set(urls_in(payload)))
    referenced_pdfs = sorted(u for u in urls if re.search(r"\.pdf(?:$|[?#])", u, re.I))
    download = detail.get("download")
    downloads = [urljoin(page_url, download)] if download else []
    downloads.extend(urljoin(page_url, n.attrs["href"]) for n in nodes if n.tag == "a" and n.attrs.get("href") and n.attrs.get("title") == "Download slidedeck")
    pdfs = sorted({u for u in downloads if re.search(r"\.pdf(?:$|[?#])", u, re.I)})
    wrappers = sorted(u for u in urls if urlparse(u).hostname == "notist.ninja")
    resources = detail.get("resources", {}).get("data", [])
    tweets = [n for n in nodes if n.tag == "blockquote" and n.hasclass("twitter-tweet")]
    feedback = [{"text": clean(n.text()), "links": sorted(set(html_urls(type("D", (), {"root": n})(), page_url)))} for n in tweets]
    headings = [clean(n.text()) for n in nodes if n.tag in ("h2", "h3")]
    events = [r for r in record.get("relationships", {}).get("data", []) if r.get("type") == "events"]
    deck_types = sorted(set(d.get("type", "unknown") for d in decks))
    if pdfs:
        pdf_state = "download_link_exposed"
    elif len(slide_nodes) == 1 or len(slides) == 1:
        pdf_state = "single_image_only_review"
    elif slide_nodes or slides or "images" in deck_types:
        pdf_state = "original_pdf_link_not_exposed"
    elif decks or any("embedded-deck" in n.attrs.get("class", "") and not n.hasclass("embedded-video") for n in nodes):
        pdf_state = "external_deck_inspect_original"
    else:
        pdf_state = "no_deck_observed"
    result = {
        "id": ident, "title": attrs.get("title"), "url": page_url,
        "presented_on": attrs.get("presented_on"), "published_on": attrs.get("published_on"),
        "timezone": attrs.get("timezone"), "listing": summary,
        "page_status": page_receipt.get("status"), "json_status": json_receipt.get("status"),
        "detail": record, "pdf_state": pdf_state, "pdf_urls": pdfs,
        "reference_pdf_urls": sorted(set(referenced_pdfs) - set(pdfs)),
        "non_pdf_download_urls": sorted(set(downloads) - set(pdfs)),
        "deck_types": deck_types, "json_slide_count": len(slides), "html_slide_count": len(slide_nodes),
        "slide_type_counts": {t: sum(s.get("type") == t for s in slides) for t in sorted(set(s.get("type", "unknown") for s in slides))},
        "html_slide_ids": [n.attrs.get("data-hash") for n in slide_nodes],
        "resources": resources, "feedback": feedback, "headings": headings,
        "iframe_urls": [urljoin(page_url, n.attrs["src"]) for n in nodes if n.tag == "iframe" and n.attrs.get("src")],
        "embed_wrappers": wrappers, "event_ids": [e["id"] for e in events],
        "urls": urls,
        "issues": [],
    }
    if page_receipt.get("status") != 200 or not record:
        result["issues"].append("page_or_json_unavailable")
    if len(slides) != len(slide_nodes) and (slides or slide_nodes):
        result["issues"].append("html_json_slide_count_differs")
    if tweets:
        result["issues"].append("feedback_requires_html_preservation")
    if wrappers:
        result["issues"].append("resolve_notist_embed_dependency")
    print(f"{ident}: {pdf_state}; {len(slides)} slides; {len(resources)} resources; {len(tweets)} feedback", flush=True)
    return result


def write_csv(name, rows, fields):
    with (OUT / name).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    initial = {}
    for name, url in (
        ("profile.html", BASE + "/"), ("profile.json", "https://noti.st/phrawzty.json"),
        ("presentations.html", BASE + "/presentations"), ("presentations.json", BASE + "/presentations.json"),
        ("bio.html", BASE + "/bio"), ("videos.html", BASE + "/videos"),
    ):
        initial[name], _ = fetch(url, name)
    summaries = parse_json(initial["presentations.json"]).get("data", [])
    profile = parse_json(initial["profile.json"]).get("data", [])
    profile_talks = [r for a in profile for r in a.get("relationships", {}).get("data", []) if r.get("type") == "presentations"]
    by_id = {r["id"]: r for r in profile_talks + summaries if r.get("type") == "presentations"}
    archive_ids = set(re.findall(r'href="/([A-Za-z0-9]{6})/[^\"]+"', initial["presentations.html"])) - {"assets"}
    for ident in sorted(archive_ids - {k.removeprefix("pr_") for k in by_id}):
        by_id["pr_" + ident] = {"id": "pr_" + ident, "type": "presentations", "links": {"self": BASE + "/" + ident}, "attributes": {}}
    talks = parallel(audit_talk, list(by_id.values()))
    save_json(OUT / "presentations.json", talks)
    event_urls = sorted({s.get("links", {}).get("event") for s in summaries + profile_talks if s.get("links", {}).get("event")})
    def fetch_event(url):
        ident = urlparse(url).path.rsplit("/", 1)[-1]
        data, receipt = fetch(url, "events/" + ident)
        parsed = parse_json(data)
        event = next(iter(parsed.get("data", [])), {})
        page_url = event.get("links", {}).get("self")
        page_receipt = {}
        if page_url:
            _, page_receipt = fetch(page_url, "events/" + ident.replace(".json", ".html"))
        return {"url": url, "status": receipt.get("status"), "html_status": page_receipt.get("status"), "data": parsed}
    events = parallel(fetch_event, event_urls)
    video_ids = sorted(set(re.findall(r'href="/videos/([A-Za-z0-9]{6})"', initial["videos.html"])))
    def fetch_video(ident):
        url = BASE + "/videos/" + ident
        source, receipt = fetch(url, f"videos/{ident}.html")
        doc = Document(source)
        return {"id": ident, "url": url, "status": receipt.get("status"), "urls": sorted(set(html_urls(doc, url)))}
    videos = parallel(fetch_video, video_ids)
    photo_ids = sorted(set(re.findall(r'href="/photo/([A-Za-z0-9]{6})"', initial["bio.html"])))
    def fetch_photo(ident):
        url = BASE + "/photo/" + ident
        source, receipt = fetch(url, f"photos/{ident}.html")
        doc = Document(source)
        return {"id": ident, "url": url, "status": receipt.get("status"), "text": clean(doc.root.text()), "urls": sorted(set(html_urls(doc, url)))}
    photos = parallel(fetch_photo, photo_ids)
    wrappers = sorted({u for talk in talks for u in talk["embed_wrappers"]} | {u for video in videos for u in video["urls"] if urlparse(u).hostname == "notist.ninja"})
    def fetch_wrapper(url):
        key = hashlib.sha256(url.encode()).hexdigest()[:20]
        source, receipt = fetch(url, f"embeds/{key}.html")
        urls = sorted(set(html_urls(Document(source), url)))
        return {"url": url, "status": receipt.get("status"), "resolved_urls": urls}
    resolved = parallel(fetch_wrapper, wrappers)
    resolved_by_url = {r["url"]: r["resolved_urls"] for r in resolved}
    for talk in talks:
        talk["resolved_embeds"] = [{"wrapper": u, "destinations": resolved_by_url.get(u, [])} for u in talk["embed_wrappers"]]
        destinations = [u for r in talk["resolved_embeds"] for u in r["destinations"]]
        if talk["pdf_state"] == "external_deck_inspect_original" and destinations and all(urlparse(u).hostname in ("www.youtube.com", "www.youtube-nocookie.com", "player.vimeo.com") for u in destinations):
            talk["pdf_state"] = "video_only_no_slide_deck_observed"
    save_json(OUT / "presentations.json", talks)
    pdf_urls = sorted({u for talk in talks for u in talk["pdf_urls"]})
    def check_pdf(url):
        _, receipt = fetch(url, method="HEAD")
        return receipt
    pdf_checks = parallel(check_pdf, pdf_urls)
    reference_pdf_urls = sorted({u for talk in talks for u in talk["reference_pdf_urls"]})
    reference_pdf_checks = parallel(check_pdf, reference_pdf_urls)
    save_json(OUT / "events.json", events)
    save_json(OUT / "videos.json", videos)
    save_json(OUT / "photos.json", photos)
    save_json(OUT / "embeds.json", resolved)
    save_json(OUT / "pdf-link-checks.json", pdf_checks)
    save_json(OUT / "reference-pdf-link-checks.json", reference_pdf_checks)
    save_json(OUT / "requests.json", sorted(RECEIPTS, key=lambda r: (r["url"], r["method"])))
    rows = [{**t, "pdf_urls": " | ".join(t["pdf_urls"]), "deck_types": " | ".join(t["deck_types"]),
             "resource_count": len(t["resources"]), "feedback_count": len(t["feedback"]),
             "embed_count": len(t["embed_wrappers"]), "issues": " | ".join(t["issues"])} for t in talks]
    fields = ["id", "title", "presented_on", "url", "pdf_state", "pdf_urls", "deck_types", "json_slide_count", "html_slide_count", "resource_count", "feedback_count", "embed_count", "issues"]
    write_csv("inventory.csv", rows, fields)
    write_csv("pdf-actions.csv", [r for r in rows if r["pdf_state"] != "download_link_exposed"], fields[:8])
    write_csv("missing-pdf-links.csv", [r for r in rows if r["pdf_state"] == "original_pdf_link_not_exposed"], fields[:8])
    # Superseded: a missing public URL does not establish a disabled setting.
    (OUT / "enable-downloads.csv").unlink(missing_ok=True)
    all_urls = {u for t in talks for u in t["urls"]}
    for name, source in initial.items():
        if name.endswith(".html"):
            all_urls.update(html_urls(Document(source), BASE + "/"))
        else:
            all_urls.update(urls_in(parse_json(source)))
    all_urls.update(u for p in photos for u in p["urls"])
    all_urls.update(u for v in videos for u in v["urls"])
    all_urls.update(u for r in resolved for u in r["resolved_urls"])
    asset_rows = []
    for url in sorted(all_urls):
        parsed = urlparse(url)
        if parsed.hostname in ("on.notist.cloud", "notist.ninja") or re.search(r"\.(pdf|png|jpg|jpeg|gif|webp|svg|mp4|webm)(?:$|[?#])", url, re.I):
            asset_rows.append({"url": url, "host": parsed.hostname, "body_downloaded": False,
                               "presentation_ids": " | ".join(t["id"] for t in talks if url in t["urls"])})
    write_csv("asset-references.csv", asset_rows, ["url", "host", "body_downloaded", "presentation_ids"])
    counts = {state: sum(t["pdf_state"] == state for t in talks) for state in sorted(set(t["pdf_state"] for t in talks))}
    summary = {
        "audited_at": datetime.now(timezone.utc).isoformat(), "scope": "public portfolio only", "canonical_target": "https://portfolio.dark.ca",
        "presentation_count": len(talks), "profile_listing_count": len(profile_talks), "archive_json_count": len(summaries), "archive_html_count": len(archive_ids),
        "listing_id_sets_agree": {t["id"] for t in summaries} == {t["id"] for t in profile_talks} == {"pr_" + x for x in archive_ids},
        "pdf_states": counts, "unique_pdf_links": len(pdf_urls), "pdf_bodies_downloaded": 0,
        "exposed_original_pdf_bytes_from_headers": sum(int(p.get("content_length") or 0) for p in pdf_checks),
        "original_pdfs_over_pages_25_mib_limit": [{"url": p["url"], "bytes": int(p["content_length"]),
            "presentation_ids": [t["id"] for t in talks if p["url"] in t["pdf_urls"]]}
            for p in pdf_checks if int(p.get("content_length") or 0) > 25 * 1024 * 1024],
        "pdf_head_failures": [p for p in pdf_checks if p.get("status") != 200],
        "reference_pdf_head_failures": [p for p in reference_pdf_checks if p.get("status") != 200],
        "event_count": len(events), "video_index_entries": len(videos), "headshots": len(photos),
        "slides_in_json": sum(t["json_slide_count"] for t in talks), "resource_count": sum(len(t["resources"]) for t in talks),
        "feedback_post_count": sum(len(t["feedback"]) for t in talks),
        "embed_wrappers": len(resolved), "unresolved_embeds": [r for r in resolved if r.get("status") != 200 or not r["resolved_urls"]],
        "asset_reference_count": len(asset_rows), "request_failures": [r for r in RECEIPTS if "error" in r],
        "slide_count_discrepancies": [t["id"] for t in talks if "html_json_slide_count_differs" in t["issues"]],
        "limitations": ["HEAD checks do not establish full PDF integrity; no PDF or media bodies downloaded.",
                        "External resource destinations have been inventoried, not exhaustively fetched or archived.",
                        "A missing PDF link is a candidate for enabling downloads, not proof an original exists.",
                        "Only public listings were used; no private or unlisted account data accessed."]
    }
    save_json(OUT / "summary.json", summary)
    write_report(summary, talks)
    print(json.dumps(summary, indent=2), flush=True)


def write_report(summary, talks):
    lines = [
        "PUBLIC PORTFOLIO AUDIT — 2026-11-05", "",
        "Source: https://speaking.dark.ca (Notist). Target canonical: https://portfolio.dark.ca.",
        "Scope: public portfolio only. No private/unlisted account access or account/hosting changes.",
        "", "RESULTS", "",
        f"{len(talks)} presentations; public listing ID sets agree: {summary['listing_id_sets_agree']}.",
        f"{summary['event_count']} events; {summary['video_index_entries']} video-index entries; {summary['headshots']} headshots.",
        f"{summary['slides_in_json']} slides; {summary['resource_count']} resources; {summary['feedback_post_count']} feedback posts.",
        f"{summary['embed_wrappers']} embed wrappers inspected; {len(summary['unresolved_embeds'])} unresolved.",
        f"HTML/JSON slide-count discrepancies: {summary['slide_count_discrepancies']}",
        "", "PDF STATUS", "",
        json.dumps(summary["pdf_states"], indent=2),
        f"{summary['unique_pdf_links']} distinct original PDF URLs. Original PDF HEAD failures: {len(summary['pdf_head_failures'])}.",
        f"Original PDF headers total {summary['exposed_original_pdf_bytes_from_headers']:,} bytes, excluding unexposed originals.",
        "No PDF or media bodies have been downloaded. HEAD success is not proof of file integrity.",
        "", "INVESTIGATE MISSING ORIGINAL PDF LINKS", "",
        "The public page and JSON do not expose original-PDF URLs for these decks. The account setting is unknown unless reported below.",
        "The owner reports downloads already enabled for HZ4wld and PvNrMj (2026-11-05). Do not infer a disabled setting from download:null.",
        "Fresh public JSON checks for these two decks still returned download:null, including responses with Age: 0.",
        "Investigate original-file availability, inconsistent download flags, and cached state before asking for bulk setting changes.",
        "If no original is present, record that explicitly; a reconstructed PDF does not count as recovered.",
    ]
    for talk in talks:
        if talk["pdf_state"] == "original_pdf_link_not_exposed":
            event = next((r.get("attributes", {}).get("title", "") for r in talk["detail"].get("relationships", {}).get("data", []) if r.get("type") == "events"), "")
            lines.extend([f"[ ] {talk['presented_on'][:10]} — {talk['title'].strip()} — {event}", "    " + talk["url"]])
    lines.extend(["", "OTHER PRESENTATIONS WITHOUT AN OBSERVED ORIGINAL PDF", "",
                  "These are not confirmed missing PDFs. Review whether a deck should exist; preserve public content regardless."])
    for state in ("single_image_only_review", "video_only_no_slide_deck_observed", "no_deck_observed"):
        lines.extend(["", state + ":"])
        for talk in talks:
            if talk["pdf_state"] == state:
                lines.extend([f"- {talk['presented_on'][:10]} — {talk['title'].strip()}", "  " + talk["url"]])
    lines.extend(["", "RECOVERY AND HOSTING ISSUES", "",
        "Exposed originals exceeding Cloudflare Pages' 25 MiB asset limit:"])
    for pdf in summary["original_pdfs_over_pages_25_mib_limit"]:
        lines.append(f"- {', '.join(pdf['presentation_ids'])}: {pdf['bytes'] / 1024 / 1024:.2f} MiB — {pdf['url']}")
    lines.extend([
        "Cloudflare reference: https://developers.cloudflare.com/pages/platform/limits/#file-size",
        "Plan: keep Git-triggered Pages deployment for the site; link large original PDF downloads from GitHub Releases.",
        "Do not recompress or replace preserved originals to satisfy the deployment limit.",
        "", "External-reference PDF HEAD failures (these are not original slide decks):",
    ])
    for check in summary["reference_pdf_head_failures"]:
        lines.append(check["url"] + " — " + check.get("error", str(check.get("status"))))
    lines.extend([
        "A later GET/browser check is required before calling a HEAD-rejected resource unavailable.",
        "Feedback is preserved as available HTML/text and links. Linked social-media images are not yet recovered.",
        "External links and third-party media bodies have not been exhaustively fetched or verified.",
        "Some presentation variants reuse an original PDF; retain each presentation's independent metadata and slide state.",
        "", "FILES", "",
        "missing-pdf-links.csv: original PDFs not exposed publicly; this does not establish disabled download settings.",
        "pdf-actions.csv: all presentations without an exposed original PDF, with reason categories.",
        "inventory.csv / presentations.json: presentation metadata, slide state, resources, feedback, and URLs.",
        "events.json / videos.json / photos.json / embeds.json: supporting records and resolved embed destinations.",
        "asset-references.csv: discovered asset references; bodies remain undownloaded.",
        "pdf-link-checks.json / reference-pdf-link-checks.json: original-deck and external-reference HEAD checks.",
        "raw/: untouched HTML/JSON responses. requests.json: timestamps, HTTP outcomes and SHA-256 evidence hashes.",
        "summary.json: counts, limitations and oversized-original report.",
        "", "NEXT", "",
        "Download every exposed original completely, validate every page, and investigate recovery routes for unexposed originals.",
    ])
    (OUT / "README.txt").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
