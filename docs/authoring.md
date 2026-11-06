# Authoring reference

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

For scripting, explicit commands still work with the Markdown path, its readable filename stem, or its stable ID. For example, `uv run portfolio slides content/appearances/2024-09-25-devopsdays-cairo-2024.md ~/presentations/revised.pdf`. Supplying just a PDF path, as in `uv run portfolio slides ~/presentations/revised.pdf`, opens the talk chooser.

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


## Appearance filenames and public URLs

Appearance Markdown uses readable `YYYY-MM-DD-event.md` filenames, with numeric suffixes for multiple talks at the same event/date. Files can be renamed without changing their public URLs: `path` and `extra.id` remain stable, as do aliases and deck references. Title/event edits do not automatically rename existing files.

The CLI resolves stable IDs from front matter rather than assuming they are filenames. Explicit Markdown paths and readable stems work too; IDs take precedence if a stem happens to match another entry’s ID. New entries get readable filenames even when a script supplies a custom `--id`. The importer resumes by stable ID, so renamed entries are not imported again.
