# Speaking portfolio

A Zola speaking portfolio for **portfolio.dark.ca**, with `speaking.dark.ca` retained for existing links. Launch status and remaining dashboard steps are tracked in the [launch checklist](deploy/launch-checklist.md).

## Setup

Install [uv](https://docs.astral.sh/uv/), Zola **0.23.6**, Poppler and Git. On macOS: `brew install uv zola poppler`.

Clone the source and assets alongside each other:

```sh
cd ~/repos
git clone https://github.com/phrawzty/portfolio.dark.ca.git
git clone https://github.com/phrawzty/assets.dark.ca.git
cd portfolio.dark.ca
uv sync --frozen
uv run portfolio doctor
uv run portfolio assets fetch
uv run portfolio
```

`assets fetch` verifies the recorded assets commit. If your assets clone is newer than this portfolio revision, it leaves it alone and explains how to switch revisions or record your newer assets.

## Everyday use

`uv run portfolio` opens the menu. Choose talks by title, event or date; no internal IDs are needed. You can also edit the Markdown files in `content/appearances/` directly.

- **New talk:** answer the prompts and edit the description. New entries start as drafts. An upcoming talk needs no slides.
- **Repeat a talk:** copies its description/resources and starts without slides. At the PDF prompt, Enter means no slides; type `reuse` explicitly to reuse the earlier deck.
- **Add or replace slides:** choose the talk and drag in a PDF. Processing happens locally, and older deck versions stay intact.
- **Add a recording / Edit slide notes:** choose the talk; notes override the displayed text without changing the PDF.
- **Preview:** opens a local server at [127.0.0.1:1112](http://127.0.0.1:1112/) with drafts included and automatic rebuild/reload.
- **Check:** validates metadata, slide references and asset checksums and explains any failure. It does not upload anything.

Direct commands are interactive too:

```sh
uv run portfolio edit
uv run portfolio slides
uv run portfolio recording
uv run portfolio notes
uv run portfolio preview
```

See the [authoring reference](docs/authoring.md) for resources, feedback, repeats, locations and scripting.

## Publish

For a new draft with slides:

```sh
uv run portfolio publish
uv run portfolio assets publish
uv run portfolio build
git add content data notes
git commit
git push
```

`publish` marks the chosen draft ready; it does not deploy. `assets publish` commits/pushes only referenced public files in the companion assets repo, then updates `data/assets-lock.json`. The final portfolio push triggers Cloudflare once its integration is configured. Existing public text-only edits need neither a new assets commit nor the draft-publication step.

The assets checkout can also be committed manually. Leave unrelated staged changes out of the menu's assets commit. Both repositories use normal Git and can be mirrored elsewhere.

## Files and hosting

- `content/`: editable appearances, reusable talk descriptions and biography.
- `data/`: deck metadata, checksums, map data and the pinned assets revision.
- `notes/`: optional slide-text/title overrides.
- `templates/`, `static/`, `themes/`: the Zola site and Terminus appearance shared with dark.ca.
- `../assets.dark.ca/files/decks/<date-title-event>/`: the PDF and its `slides/` images together; unchanged repeats share a folder, revisions receive new stable names.
- `../assets.dark.ca/files/speaker/`: headshots.

Cloudflare serves the website and slide images. PDF downloads use the HTTP base URL in `portfolio.toml` (currently GitHub raw URLs pinned to the assets commit). All binaries are ordinary Git files. Builds run offline after restoring the assets checkout and do no PDF processing.

Generated `public/` and `.portfolio/` files are disposable and ignored. Hard links share the asset bytes, so separate `du` totals for the two checkouts overlap.

## Deployment and checks

Use the [launch checklist](deploy/launch-checklist.md) and [deployment/rollback guide](deploy/README.md) for Cloudflare, CARTO, DNS and hosted acceptance checks.

```sh
uv run portfolio check
uv run python -m unittest discover -s tests -v
node tests/test_frontend.mjs
```

The ignored Noti.st migration material is separate from normal maintenance. Its retention decision and restore procedure are documented in the [assets repo migration notes](https://github.com/phrawzty/assets.dark.ca/blob/main/docs/migration.md).
