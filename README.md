# portfolio.dark.ca

My speaking portfolio. Built with Zola and deployed through Cloudflare Pages.

## Setup

Requires Git, [uv](https://docs.astral.sh/uv/), Zola 0.23.6 and Poppler.

Clone both repositories into the same parent directory:

```sh
git clone https://github.com/phrawzty/portfolio.dark.ca.git
git clone https://github.com/phrawzty/assets.dark.ca.git
cd portfolio.dark.ca
uv sync --frozen
uv run portfolio doctor
uv run portfolio assets fetch
```

## Authoring

```sh
uv run portfolio
```

The menu handles talks, slides, recordings, slide notes, previews and publication. You can also edit the Markdown in `content/` directly.

- New appearances start as drafts. Slides are optional.
- Repeating a talk copies its description and resources. Press Enter at the PDF prompt to leave slides empty, or type `reuse` to use the previous deck.
- Adding slides processes the PDF locally. Replacing a deck leaves previous appearances unchanged.
- Slide notes override displayed text without modifying the PDF.
- Known locations are reused. New ones are found and confirmed interactively; type `Virtual` or `Online` to omit the map pin.

Run `uv run portfolio --help` for direct commands and scripting options. In particular, `uv run portfolio remove` removes a cancelled appearance after confirmation but leaves shared talks, locations and assets intact.

Appearance filenames use `YYYY-MM-DD-event.md`. Their public URLs are set separately in front matter; keep `path`, `extra.id` and aliases unchanged when renaming files.

Add resources and feedback to an appearance’s front matter:

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

Location search offers retry, OpenStreetMap URL and manual-coordinate fallbacks. To add or correct a place separately, run:

```sh
uv run portfolio place 'City, Country'
```

Use `uv run portfolio place --help` for noninteractive coordinates and stable-ID updates. Automated authoring resolves saved locations only; it never geocodes without confirmation. Search data is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.

## Preview

```sh
uv run portfolio preview
```

Open [localhost:1112](http://127.0.0.1:1112/). Drafts are included; changes rebuild automatically.

## Publish

Choose **Publish changes** from the menu, or run:

```sh
uv run portfolio publish
```

Choose a draft, or choose current changes for edits to something already published. The command detects whether referenced assets changed and shows the plan. Confirm once; it then runs the production build, creates the necessary Git commits, pushes assets first when needed and pushes the portfolio to trigger deployment.

The lower-level `uv run portfolio assets publish` command is available for recovery, but is not part of the normal workflow.

## Hosting

Cloudflare Pages builds `main` using:

| Setting | Value |
| --- | --- |
| Build command | `sh scripts/cloudflare-build.sh` |
| Output directory | `public` |
| Environment variable | `ZOLA_VERSION=0.23.6` |

The build fetches the assets commit recorded in `data/assets-lock.json`. Cloudflare serves slide images; PDF downloads use the URL configured in `portfolio.toml`.

`portfolio.dark.ca` is canonical. A Cloudflare Redirect Rule sends `speaking.dark.ca` there, preserving paths and query strings. The CARTO key’s website restrictions must allow the hostname displaying the map.

To roll back immediately, select a previous successful production deployment in Cloudflare Pages. For a lasting correction, revert the source commit and push. Keep referenced assets commits available.

## Checks

```sh
uv run portfolio check
uv run python -m unittest discover -s tests -v
node tests/test_frontend.mjs
```

Generated files in `public/` and `.portfolio/` are ignored and disposable.
