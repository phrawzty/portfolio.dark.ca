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

The interactive menu handles talks, slides, recordings, slide notes and previews. You can also edit the Markdown in `content/` directly.

- New appearances start as drafts. Slides are optional.
- Repeating a talk copies its description and resources. Press Enter at the PDF prompt to leave slides empty, or type `reuse` to use the previous deck.
- Adding slides processes the PDF locally. Replacing a deck leaves previous appearances unchanged.
- Slide notes override displayed text without modifying the PDF.

Remove a cancelled appearance with its stable ID (or its Markdown path):

```sh
uv run portfolio remove 2026-11-23-devopsdays-warsaw-2026
```

The command asks for confirmation. For scripts, pass `--yes`; this removes only
the appearance Markdown file. Shared talk pages, locations, deck metadata, and
assets stay in place. An unused location is not rendered as a map pin.

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

When asked `Location (city, country; or Virtual):`, type a place name. Known
places resolve locally, ignoring case; an ambiguous name prompts a choice.
For a new place, the tool searches Nominatim, asks you to confirm a result,
and saves the name and coordinates in this portfolio's `data/places.toml`.
Type `Virtual` or `Online` to skip the map.

New IDs use `city-<two-letter-country>`, for example `rio-de-janeiro-br`.
State/region text remains in the display name, not the generated ID. Nominatim
supplies the country code; manual coordinate entry prompts for it. Existing IDs
remain stable when names are edited. An ID collision is reported for manual review.

Each in-person appearance references one stable place ID:

```toml
[extra]
place = "paris-fr"
# Optional; otherwise the registry's name is displayed:
location_label = "Paris, France · Venue name"
```

The registry is independent of the travel map. Editing a display label never
changes a pin. Appearances sharing a place share one pin. Checks and builds
reject missing places, invalid coordinates, and legacy inline locations.

New-place searches use the free public Nominatim service, with no account or API
key. The tool identifies itself, caches responses under `.portfolio/geocoding/`,
and limits requests to at most one per second. Searches happen only after a
submitted name, never as autocomplete or during checks/builds. Search data is
© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), ODbL.
See the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).
The Nominatim-compatible endpoint is configurable in `portfolio.toml` under
`[geocoding]`, so providers can be changed without a software update.

If search fails or finds the wrong place, refine the search, paste an
OpenStreetMap URL, or enter coordinates directly without leaving authoring.
You can also maintain places separately:

```sh
uv run portfolio place 'City, Country'
```

For offline use, supply coordinates explicitly. Use `--id` to update an existing
place by its stable reference, including when changing its name:

```sh
uv run portfolio place 'City, Country' --country-code fr \
  --map-url 'https://www.openstreetmap.org/#map=12/48.85/2.35'
```

```sh
uv run portfolio place 'Paris, France' --id paris-fr \
  --latitude 48.856614 --longitude 2.352222
```

Noninteractive `new --location` resolves known names or IDs locally. Add an
unknown place first with `portfolio place`; scripts never silently geocode or
accept an unconfirmed search result.

## Preview

```sh
uv run portfolio preview
```

Open [localhost:1112](http://127.0.0.1:1112/). Drafts are included; changes rebuild automatically.

## Publish

Mark a draft ready using the menu or `uv run portfolio publish`.

If assets changed, commit and push them first:

```sh
uv run portfolio assets publish
```

This also updates `data/assets-lock.json` with the assets commit.

Then build, commit and push the portfolio:

```sh
uv run portfolio build
git add content data notes
git commit
git push
```

Pushing `main` triggers deployment. Text-only edits to published appearances need only the final build, commit and push.

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
