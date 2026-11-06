# Speaking portfolio

An actively maintained Zola portfolio at **portfolio.dark.ca**, using the same Terminus appearance as dark.ca. `speaking.dark.ca` is retained as a legacy hostname. Nothing here has been deployed yet.

## Everyday use

Install [uv](https://docs.astral.sh/uv/), Zola **0.23.6**, and Poppler. On macOS, Zola and Poppler are available through `brew install zola poppler`. Clone `phrawzty/portfolio.dark.ca` into `~/repos/portfolio.dark.ca` and `phrawzty/assets.dark.ca` into `~/repos/assets.dark.ca`. Then, from the portfolio checkout:

```sh
uv sync --frozen
uv run portfolio doctor
uv run portfolio assets fetch
uv run portfolio
```

`uv run portfolio` opens a small menu: create a talk, repeat a previous talk at another event, edit its Markdown, add slides, add a recording, edit slide notes, or preview the site. Existing talks are listed by **title, event, and date**; type a word or year to narrow the list. You never need to look up an ID.

Choose **New talk** and answer the prompts. You can add a PDF immediately (drag it into the terminal), or press Enter to add slides later. The script creates the Markdown file and opens it in `$VISUAL`, `$EDITOR`, or your system text editor. Write the description below the second `+++`; the script fills in the metadata. New talks start as drafts, and upcoming talks do not need slides.

You can also go straight to a task:

```sh
uv run portfolio edit
uv run portfolio slides
uv run portfolio recording
uv run portfolio preview
```

The first three commands ask you to choose a talk. `slides` then asks for the PDF; `recording` asks for its URL. `edit` opens the Markdown file. You can always open and edit the files in `content/appearances/` directly instead.

Preview is at `http://127.0.0.1:1112`, includes drafts, and rebuilds/reloads when source files change. PDF processing happens only when you run `slides`, never during preview or deployment. Every page is rendered locally; original PDF bytes are retained, text is extracted, and lossless WebP slides are generated. Re-adding the same PDF reuses its processed version.

When ready:

```sh
uv run portfolio publish
uv run portfolio assets publish
uv run portfolio build
git add content data notes
git commit
git push
```

`publish` lets you choose a draft to include in production builds; it does not deploy. The menu calls this **Mark a draft ready for publication**. Choose **Commit and push public assets** (menu option 10) before committing new slides. This uses ordinary Git to commit the files referenced by public talks in the assets checkout, pushes them to its configured remote, and records that commit in `data/assets-lock.json`. Draft-only files and unrelated staged changes are not included. Text-only edits and talks without slides need no assets commit.

## Repeat a talk or add a recording

```sh
uv run portfolio repeat
uv run portfolio slides
uv run portfolio recording
```

A repeat copies the description and resources, and starts **without slides**. At the PDF prompt, press Enter to leave it without slides, provide a PDF to add a new deck, or explicitly type `reuse` to copy the previous event's deck. Its event, date, recording, and feedback remain independent. Attaching a revised PDF changes only that appearance; old appearances keep their old deck versions. Reusable talk descriptions live in `content/talks/`.

For noninteractive scripts, deck reuse also requires an explicit choice: `portfolio new --from … --reuse-slides`.

To correct a transcription or add slide notes:

```sh
uv run portfolio notes
```

Choose the talk and its notes file opens in your editor. It overrides slide text/titles for that deck version without modifying source PDFs or images. No migration JSON needs hand-editing.

For scripting, explicit commands still work with either the Markdown path or its filename stem. For example, `uv run portfolio slides content/appearances/QfIYtz.md ~/presentations/revised.pdf`. Supplying just a PDF path, as in `uv run portfolio slides ~/presentations/revised.pdf`, opens the talk chooser.

Resources and feedback belong in the appearance's TOML front matter:

```toml
[[extra.resources]]
title = "Related project"
url = "https://example.com/"
description = "Why this is useful."

[[extra.feedback]]
text = "The quoted feedback."
author = "Author name"
url = "https://example.com/original-post"
```

## Locations

Map pins derive from appearance records. Locations already in `data/places.toml` resolve locally; imported appearances retain their recorded coordinates. New locations can be saved once by pasting an OpenStreetMap link centered on the city:

```sh
uv run portfolio place 'Example City, Country' --map-url 'https://www.openstreetmap.org/#map=12/48.85/2.35'
```

Unknown locations remain readable in the archive and simply have no pin until saved. There is no required geocoding account or network lookup. The map uses the existing CARTO tile configuration from dark.ca; allow the new hostname in that key's domain restrictions before launch. The textual archive works independently of map tiles.

## Assets and Cloudflare

The website, slide images and headshots are served by Cloudflare Pages. All website PDFs and images are **ordinary Git files** in the companion `assets.dark.ca` repository. A normal clone contains the actual bytes; no Releases, Git LFS, GitHub CLI, or separate download service is needed to restore them. Either repository can be cloned or mirrored to any Git host.

Each deck version is a readable directory containing its PDF and slide images:

```text
files/decks/2018-06-01-serverless-revealed-dotscale-2018/
  2018-06-01-serverless-revealed-dotscale-2018.pdf
  slides/
    001.jpg
    002.jpg
```

Repeating an unchanged deck reuses its folder. A revision for the same event/title receives `-v2`, `-v3`, etc. Folder names are chosen once: later title edits do not rename existing assets. Image-only entries have a `slides/` folder without a PDF. Descriptions, transcripts, editable slide notes and integrity checksums stay in the portfolio metadata; hashes do not determine asset directory names. Headshots have readable names under `files/speaker/`.

The imported records contain 61 distinct binary bundles across 67 display records. Text-only display differences share a bundle. One PDF has two image exports, so its two version folders contain the same PDF bytes (one shared Git blob).

The daily workflow is:

1. Add or edit talks with the menu or Markdown.
2. If adding slides, mark the appearance ready, then choose **Commit and push public assets** (or run `uv run portfolio assets publish`). It commits only referenced public files with regular Git and pushes using the assets checkout's configured remote.
3. Commit the portfolio content, metadata and `data/assets-lock.json`, then push this repository.

You can instead commit and push assets manually, then run `portfolio assets publish` to record the current assets commit. Unrelated staged changes must be committed or unstaged first. No assets commit is needed for a text edit.

`data/assets-lock.json` pins the assets commit used by a portfolio revision. `portfolio assets fetch` clones that commit if the companion checkout is missing and verifies its bytes. It refuses to reset an existing checkout at another revision; fetch/switch it yourself, or publish the newer assets. Your normal author checkout can stay on `main`. Cloudflare uses a shallow checkout of the pinned revision; local clones can retain the full history.

`portfolio build` works offline, checks every required file against its SHA-256 and its Git blob in the pinned commit, and stages only images for Cloudflare. Local previews also serve the PDFs. Production PDF links use `[assets].public_base_url` from `portfolio.toml`; `{revision}` is expanded to the recorded assets commit. The initial URL uses GitHub's raw-file host. To serve PDFs from your own HTTP mirror, point that setting at the directory serving `files/` with the same relative paths. A plain Git clone contains everything needed for that mirror.

Four original PDFs exceed Cloudflare Pages' 25 MiB per-file limit, so production PDF downloads stay outside Pages; no PDF is recompressed. All current files fit GitHub's ordinary-Git file limit. The large originals are tracked directly, as requested.

`[assets].repository` configures the Git URL used on fresh builds, and `[assets].directory` defaults to `../assets.dark.ca/files`. Existing checkouts push using their normal Git remote configuration. Staging and preview use hard links where available to avoid duplicate copies.

Cloudflare Pages configuration:

- Build command: `sh scripts/cloudflare-build.sh`
- Output directory: `public`
- Environment: `ZOLA_VERSION=0.23.6`, Python 3.11 or later.
- Custom domains: `portfolio.dark.ca` and `speaking.dark.ca` on the same project.

The generated `_redirects` retains legacy presentation and slide paths. The hostname redirect is a separate Cloudflare zone Redirect Rule: Pages' `_redirects` does not support domain-level redirects ([documentation](https://developers.cloudflare.com/pages/configuration/redirects/)). `deploy/hostname-redirect-rule.json` contains the single rule to append to the zone's existing redirect rules, preserving paths and query strings. It is not a replacement for the zone's complete ruleset.

Review the preview first, then configure domains, the zone redirect rule, and DNS. No hosting or DNS changes have been made by these scripts.

## Checks and recovery material

```sh
uv run portfolio check
uv run python -m unittest discover -s tests -v
node tests/test_frontend.mjs
```

Checks cover content, immutable asset hashes, output-route collisions, slide references, deployment file-size limits, and generated internal links. Production builds exclude drafts and do not fetch from Noti.st or process PDFs.

The menu's **Check the portfolio** action and `portfolio check` show each local validation stage, a clear PASS/FAIL result, and the draft/publication counts. Failures name the affected file or talk and stop before claiming success. A check changes nothing and uploads nothing; external link availability, PDF rendering, and visual layout are outside its scope. Generated internal link targets and deployment readiness are checked during the build.

The one-time importer is `scripts/import_notist.py`; it consumes the local recovery archive. It is never part of daily authoring or a Cloudflare build. The imported portfolio contains 79 appearances, 62 talk groupings, 67 displayed decks, 38 recording links, 53 resources, and 55 feedback entries. Every imported appearance remains independently editable.

`../assets.dark.ca/preservation/` contains the original `archive/`, `audit/`, `output/` and PDF review `tmp/` directories. They are excluded from Git and deployment. A checksum-verified snapshot is stored in the companion repository's `notist-migration-2026-11-05` Release. Its committed `preservation-manifest.json` lists every file and the archive checksum; see that repository's README for restoration. Keep the local copy too. Third-party recordings and social-media image bodies have not been mirrored.

Historical website assets also remain in the old `portfolio-assets-v1` Release, but the build and authoring tools no longer use it. Its `images-*.tar` files were bundles of slide images/headshots for the previous build-download workflow.

The one-time migration scripts resolve preservation paths in the sibling assets checkout. They are retained for recovery, not invoked during normal authoring or builds.
