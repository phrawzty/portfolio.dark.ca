# Portfolio launch checklist

Work in order. Daniel handles account dashboards and chooses archive retention; Codex handles repository changes and HTTP/build checks. Dashboard settings and actual deployments are not complete until checked here.

## 1. Repository readiness — Codex

- [x] Public site content, editable authoring workflow and grouped assets committed and pushed.
- [x] Assets are normal Git files; the portfolio records a specific assets commit.
- [x] Local production build, complete local preview and 34 workflow tests passed before launch preparation.
- [x] Readable PDF paths and complete public PDF downloads verified, including the largest original.
- [x] Migration material remains ignored with its existing Release backup; no cleanup/deletion performed.
- [x] Verify the temporary-host base URL override (35 workflow tests pass).
- [x] Publish the launch checklist, deployment guide and cleaned READMEs in both repositories.

## 2. First Cloudflare Pages deployment — Daniel, then Codex

Create/reuse a **Pages** project with Git integration in Cloudflare > Workers & Pages. Connect only `phrawzty/portfolio.dark.ca`; the build fetches the assets repo itself. Do not change existing DNS yet.

| Setting | Value |
| --- | --- |
| Project name | Choose a name; record its actual `<project>.pages.dev` URL below |
| Production branch | `main` |
| Framework preset | None (use the custom build command) |
| Root directory | Repository root / blank |
| Build command | `sh scripts/cloudflare-build.sh` |
| Build output directory | `public` |
| `ZOLA_VERSION` | `0.23.6` |
| `PYTHON_VERSION` | `3.13.3` |
| `PORTFOLIO_BASE_URL` | `https://<actual-project-name>.pages.dev` during pre-launch testing |

Set these environment variables for the production build being tested. The URL override keeps navigation/feed URLs on the temporary hostname. At canonical cutover, remove it so `zola.toml` supplies `https://portfolio.dark.ca`.

- [ ] Daniel: authorize the Cloudflare GitHub integration for the portfolio repository if needed.
- [ ] Daniel: create/reuse the project with the settings above and deploy the latest `main`.
- [ ] Record project name: **not created yet (confirmed by Daniel)**.
- [ ] Record temporary URL: **pending**.
- [ ] Record successful deployment and source commit: **pending**.
- [ ] Codex: inspect logs on failure and verify the deployed response after success.

## 3. CARTO website restrictions — Daniel, then both

Open the [CARTO Basemaps dashboard](https://dashboard.basemaps.carto.com/), sign in to the account that owns the existing key, and edit that key's website restrictions. Preserve its existing allowed sites, including dark.ca and blog.dark.ca where present.

- [ ] Add `portfolio.dark.ca` using the dashboard's supported restriction syntax.
- [ ] Add the actual Pages test hostname. If testing hashed deployment URLs too, add their exact hostname or a project-scoped wildcard if supported; avoid authorizing all of pages.dev.
- [ ] Keep any existing `speaking.dark.ca` entry during transition.
- [ ] Confirm tiles load without a watermark and city popups work on the Pages deployment.
- [ ] If the key changes, update `portfolio.toml`; otherwise no repository edit is needed.

## 4. Hosted acceptance checks — both

Codex checks HTTP responses and generated links; Daniel checks browser interactions and layout.

- [ ] Homepage, appearance list, talk groupings, video list and biography work on the test hostname.
- [ ] Slides advance with buttons/keyboard; all-slides transcript and presentation view work.
- [ ] PDF downloads work, including a PDF above 25 MiB and an image-only entry without a PDF button.
- [ ] YouTube/Vimeo recordings load after clicking; external Watch links work.
- [ ] Resources, feedback, headshots, map pins and attribution are present.
- [ ] Review mobile layout and check browser console/network failures.
- [ ] Drafts remain absent from public pages and feeds (Portugal is currently a draft).
- [ ] Legacy presentation slug redirects work, for example `/QfIYtz/statements-about-stateless`.
- [ ] Legacy slide routes preserve the slide target; no navigation goes to Noti.st.

## 5. Canonical domain and speaking.dark.ca cutover — Daniel, then Codex

- [ ] Save the current speaking.dark.ca DNS target/proxy state and relevant redirect settings before changing them.
- [ ] Add `portfolio.dark.ca` through the Pages project's Custom domains screen, complete its DNS setup and wait for HTTPS activation.
- [ ] Remove the temporary `PORTFOLIO_BASE_URL` override; redeploy and verify canonical navigation/feed URLs.
- [ ] Verify portfolio.dark.ca fully before switching the older hostname.
- [ ] Add `speaking.dark.ca` as a Pages custom domain and replace its Noti.st DNS target using the Pages-provided configuration.
- [ ] Add the single host redirect from `deploy/hostname-redirect-rule.json` to the zone's existing rules (do not replace the ruleset). Preserve path and query string.
- [ ] Codex: verify HTTPS, canonical URLs, old presentation/slide paths and query preservation on both domains; check for redirect loops.

## 6. Routine publishing and rollback — both

- [ ] Exercise draft announcement -> preview -> PDF attachment -> assets commit/push -> portfolio commit/push -> hosted result. Use an isolated test branch/project for synthetic content; publish real content only when Daniel intends it to be public.
- [ ] Confirm a normal Git push triggers Pages deployment and that its build uses the pinned assets commit.
- [ ] Record the first good production deployment and source/assets commits.
- [ ] Confirm the Pages dashboard's rollback action is available for a previous successful production deployment. Preview deployments are not rollback targets.
- [ ] Document that a source rollback restores its recorded assets revision. Leave referenced assets commits reachable.

## 7. Documentation — Codex

- [x] Keep both READMEs focused on everyday use, clone/setup, publishing and the grouped asset layout.
- [x] Put deployment settings, cutover steps and rollback instructions in `deploy/README.md`.
- [x] Keep this file as the actual launch progress record; distinguish local tests from hosted acceptance checks.
- [x] Separate migration history/backup details from normal website maintenance.

## 8. Migration and local cleanup — Daniel decides; Codex can execute

Do this after the hosted site and normal publishing work.

- [ ] Choose whether to retain the ignored local `assets.dark.ca/preservation/` directory, move it to cold storage, or rely on a verified backup. No destination is assumed.
- [ ] If moving to cold storage, copy and verify against `preservation-manifest.json` before deleting the source copy.
- [ ] Decide separately whether to keep the obsolete `portfolio-assets-v1` Release. The site no longer depends on it. Do not confuse it with the migration-backup Release.
- [ ] Remove disposable build/review caches when they are no longer in use; preserve the active preview while it is being reviewed.
- [ ] Re-measure disk usage with hard links counted across both repositories.

## References

- [Cloudflare Git integration](https://developers.cloudflare.com/pages/get-started/git-integration/)
- [Build image and version overrides](https://developers.cloudflare.com/pages/configuration/build-image/)
- [Pages custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/)
- [Pages rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/)
- [CARTO Basemaps key dashboard](https://dashboard.basemaps.carto.com/)
