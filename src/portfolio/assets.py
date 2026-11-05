"""Immutable GitHub Release assets; builds never require GitHub credentials."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import Request, urlopen


class AssetError(ValueError):
    pass


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fingerprint(bundle):
    return hashlib.sha256(json.dumps(bundle["files"], sort_keys=True).encode()).hexdigest()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def download(record, target):
    """Verify the complete response before replacing any local file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        request = Request(record["url"], headers={"User-Agent": "dark.ca-portfolio/1.0"})
        with urlopen(request, timeout=180) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if temporary.stat().st_size != record["bytes"] or digest(temporary) != record["sha256"]:
            raise AssetError(f"Downloaded asset failed checksum: {record['url']}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def extract_images(archive, destination, files):
    """Only accept the exact regular files declared by the committed manifest."""
    expected = {item["path"]: item for item in files}
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="unpack-") as work:
        work = Path(work)
        with tarfile.open(archive, "r:") as source:
            members = source.getmembers()
            names = [member.name for member in members]
            if len(set(names)) != len(names) or set(names) != set(expected):
                raise AssetError("Release archive does not match the declared image files")
            for member in members:
                relative = Path(member.name)
                if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                    raise AssetError("Unsafe path or entry in release archive")
                item = expected[member.name]
                if member.size != item["bytes"]:
                    raise AssetError(f"Wrong archive file size: {member.name}")
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as incoming, target.open("wb") as output:
                    shutil.copyfileobj(incoming, output)
                if digest(target) != item["sha256"]:
                    raise AssetError(f"Wrong archive file checksum: {member.name}")
        for relative in expected:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            (work / relative).replace(target)


class Distribution:
    def __init__(self, project):
        self.project = project
        settings = project.settings.get("assets", {})
        self.repository = settings.get("repository", "phrawzty/assets.dark.ca")
        self.tag = settings.get("release", "portfolio-assets-v1")
        self.catalog_path = project.root / "data/asset-releases.json"
        self.catalog = json.loads(self.catalog_path.read_text()) if self.catalog_path.exists() else {
            "version": 1, "repository": self.repository, "release": self.tag, "bundles": {}}
        if self.catalog["repository"] != self.repository or self.catalog["release"] != self.tag:
            raise AssetError("Asset catalog and portfolio.toml disagree about the GitHub destination")

    def record(self, bundle):
        record = self.catalog["bundles"].get(bundle["id"])
        if not record or record["fingerprint"] != fingerprint(bundle):
            raise AssetError(f"Slides for {bundle['id']} have not been uploaded. Run 'portfolio assets publish' before pushing the portfolio.")
        return record

    def fetch(self, production=False, pdfs=False):
        bundles = self.project.bundles(include_drafts=not production)
        self.project.asset_dir.mkdir(parents=True, exist_ok=True)
        cache = self.project.root / ".portfolio/downloads"
        cache.mkdir(parents=True, exist_ok=True)
        fetched = 0
        for bundle in bundles:
            images = [item for item in bundle["files"] if item["path"] != bundle.get("pdf")]
            valid = lambda item: ((self.project.asset_dir / item["path"]).is_file()
                                  and (self.project.asset_dir / item["path"]).stat().st_size == item["bytes"]
                                  and digest(self.project.asset_dir / item["path"]) == item["sha256"])
            if not all(valid(item) for item in images):
                record = self.record(bundle)["images"]
                archive = cache / record["name"]
                print(f"Downloading slide images: {bundle['id'][:16]}", flush=True)
                download(record, archive)
                extract_images(archive, self.project.asset_dir, images)
                archive.unlink()
                fetched += 1
            if pdfs and bundle.get("pdf"):
                item = next(item for item in bundle["files"] if item["path"] == bundle["pdf"])
                if not valid(item):
                    download(self.record(bundle)["pdf"], self.project.asset_dir / item["path"])
                    fetched += 1
        print(f"Assets ready ({fetched} downloads; cached files verified).")

    def gh(self, *arguments, json_output=False):
        result = subprocess.run(["gh", *arguments], text=True, capture_output=True)
        if result.returncode:
            raise AssetError(result.stderr.strip() or "GitHub CLI command failed")
        return json.loads(result.stdout) if json_output else result.stdout

    def release_assets(self):
        release = self.gh("api", f"repos/{self.repository}/releases/tags/{self.tag}", json_output=True)
        pages = self.gh("api", "--paginate", "--slurp",
                        f"repos/{self.repository}/releases/{release['id']}/assets?per_page=100", json_output=True)
        return {item["name"]: item for page in pages for item in page}

    def publish(self, include_drafts=False):
        bundles = self.project.bundles(include_drafts=include_drafts)
        work = self.project.root / ".portfolio/releases"
        work.mkdir(parents=True, exist_ok=True)
        records, uploads = {}, {}
        base = f"https://github.com/{self.repository}/releases/download/{self.tag}/"
        # Prepare and verify every local file before making any remote changes.
        for bundle in bundles:
            self.project.verify_assets(bundle)
            images = [item for item in bundle["files"] if item["path"] != bundle.get("pdf")]
            temporary = work / (bundle["id"] + ".tar")
            with tarfile.open(temporary, "w", format=tarfile.USTAR_FORMAT) as archive:
                for item in sorted(images, key=lambda item: item["path"]):
                    info = tarfile.TarInfo(item["path"])
                    info.size, info.mode, info.mtime = item["bytes"], 0o644, 0
                    with (self.project.asset_dir / item["path"]).open("rb") as stream:
                        archive.addfile(info, stream)
            checksum = digest(temporary)
            name = f"images-{checksum}.tar"
            target = work / name
            temporary.replace(target)
            image_record = dict(name=name, url=base + name, bytes=target.stat().st_size, sha256=checksum)
            uploads[name] = (target, image_record)
            record = {"fingerprint": fingerprint(bundle), "images": image_record}
            if bundle.get("pdf"):
                item = next(item for item in bundle["files"] if item["path"] == bundle["pdf"])
                name = item["sha256"] + ".pdf"
                target = work / name
                if not target.exists():
                    try:
                        target.hardlink_to(self.project.asset_dir / item["path"])
                    except OSError:
                        shutil.copyfile(self.project.asset_dir / item["path"], target)
                pdf_record = {**item, "name": name, "url": base + name}
                uploads[name] = (target, pdf_record)
                record["pdf"] = pdf_record
            records[bundle["id"]] = record
        try:
            existing = self.release_assets()
        except AssetError as error:
            if "404" not in str(error):
                raise
            self.gh("release", "create", self.tag, "--repo", self.repository,
                    "--title", "Portfolio assets", "--notes", "Content-addressed slide images and original-quality PDFs. Managed by the portfolio CLI.")
            existing = {}
        for name, (path, record) in uploads.items():
            if record["bytes"] >= 2 * 1024 ** 3:
                raise AssetError(f"{name} exceeds GitHub Releases' 2 GiB limit")
            if name not in existing:
                print(f"Uploading {name} ({record['bytes'] / 1048576:.1f} MiB)", flush=True)
                self.gh("release", "upload", self.tag, str(path), "--repo", self.repository)
        remote = self.release_assets()
        for name, (_, record) in uploads.items():
            item = remote.get(name, {})
            if item.get("size") != record["bytes"] or item.get("digest") != "sha256:" + record["sha256"]:
                # gh's release JSON omits digests on some versions; verify the public
                # bytes instead of recording an unverified remote asset.
                check = work / (name + ".verify")
                download(record, check)
                check.unlink()
        self.catalog["bundles"].update(records)
        save_json(self.catalog_path, self.catalog)
        sibling = self.project.asset_dir.parent
        if sibling != self.project.root and (sibling / ".git").is_dir():
            save_json(sibling / "catalog.json", self.catalog)
        shutil.rmtree(work)
        print(f"Published and verified {len(records)} asset bundles. Commit data/asset-releases.json with your content.")
