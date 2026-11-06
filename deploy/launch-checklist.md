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

In the current dashboard, choose **Create application → Continue to Pages → Import an existing Git repository → Get started**. The top-level **Continue with GitHub** flow creates a Worker; this repository is configured for Pages. Then select `phrawzty/portfolio.dark.ca`.

Create/reuse a **Pages** project with Git integration in Cloudflare > Workers & Pages. Connect only `phrawzty/portfolio.dark.ca`; the build fetches the assets repo itself. Do not change existing DNS yet.

| Setting | Value |
| --- | --- |
| Project name | `portfolio-dark-ca` |
| Production branch | `main` |
| Framework preset | None (use the custom build command) |
| Root directory | Repository root / blank |
| Build command | `sh scripts/cloudflare-build.sh` |
| Build output directory | `public` |
| `ZOLA_VERSION` | `0.23.6` |
| `PORTFOLIO_BASE_URL` | `https://portfolio-dark-ca.pages.dev` during pre-launch testing |

Set these environment variables for the production build being tested. Leave `PYTHON_VERSION` unset; use the provided Python >=3.11. The URL override keeps navigation/feed URLs on the temporary hostname. At canonical cutover, remove it so `zola.toml` supplies `https://portfolio.dark.ca`.

- [x] Daniel: authorize the Cloudflare GitHub integration for the portfolio repository if needed.
- [x] Daniel: create the Pages project and report a successful deployment.
- [x] Record project name: **portfolio-dark-ca**.
- [x] Record temporary URL: **https://portfolio-dark-ca.pages.dev/**.
- [x] Record the first successful deployment from Daniel's screenshot: source `2fe31b6`, deployment `724b1e84.portfolio-dark-ca.pages.dev`.
- [x] Codex: verify the deployed response after success (2026-11-06).

Hosted HTTP preflight on 2026-11-06 passed: 400 HTML routes, 119 sampled static assets, complete smallest/largest PDF downloads (0.19 / 72.70 MiB), temporary-host canonical/navigation URLs, legacy redirects and draft exclusion. Browser controls, recordings, map rendering and mobile layout remain unchecked. The local receipt is `.portfolio/hosted-check.json` (ignored).

## 3. CARTO website restrictions — Daniel, then both

Open the [CARTO Basemaps dashboard](https://dashboard.basemaps.carto.com/), sign in to the account that owns the existing key, and edit that key's website restrictions. Preserve its existing allowed sites, including dark.ca and blog.dark.ca where present.

- [x] Add `portfolio.dark.ca`; Codex verified a tile request with that Referer returns HTTP 200.
- [x] Add `portfolio-dark-ca.pages.dev`; Codex verified a tile request with that Referer returns HTTP 200. Hashed preview hostnames are separate if used later.
- [x] Daniel completed the key restriction update; retain existing allowed sites during the remaining cutover.
- [x] Daniel tested and confirmed the map works on Pages. Browser interaction coverage remains in hosted acceptance below.
- [x] Existing key continues to work; no repository key change required.

CARTO completed on 2026-11-06: Daniel updated and tested the key. Codex rechecked both portfolio-dark-ca.pages.dev and portfolio.dark.ca Referers: each now returns HTTP 200 (previously 403).

## 4. Hosted acceptance checks — both

Codex checks HTTP responses and generated links; Daniel checks browser interactions and layout.

- [x] Homepage, appearance list, talk groupings, video list and biography return successfully on the test hostname; browser layout remains below.
- [ ] Slides advance with buttons/keyboard; all-slides transcript works.
- [x] PDF downloads work, including a complete 72.70 MiB PDF matched to its SHA-256; image-only entries have no PDF button.
- [ ] YouTube/Vimeo recordings load after clicking; external Watch links work.
- [ ] Resources, feedback, headshots, map pins and attribution are present.
- [ ] Review mobile layout and check browser console/network failures.
- [x] Initial hosted test verified draft exclusion across pages/feed/sitemap/map and a 404 direct URL. Daniel has since intentionally published Portugal in `89f8bcd`; its hosted appearance is pending Git integration repair.
- [x] Legacy presentation slug redirects work, for example `/QfIYtz/statements-about-stateless`.
- [x] Sampled legacy slide route preserves its slide fragment and lands on the Pages hostname.
- [ ] Browser review: primary navigation, controls and recording actions stay on the intended destinations.

## 5. Canonical domain and speaking.dark.ca cutover — Daniel, then Codex

- [x] Save public DNS answers before cutover in `.portfolio/dns-before-cutover.json`; speaking.dark.ca still reaches the old site, and portfolio.dark.ca does not yet resolve.
- [ ] Daniel: record speaking.dark.ca proxy state and any existing redirect rules from the dashboard (public DNS cannot establish those settings).
- [x] Add `portfolio.dark.ca` through Pages, complete DNS setup and activate HTTPS. Daniel's dashboard shows Active/SSL enabled; Codex verified the served page with normal TLS certificate validation using the current public DNS address.
- [ ] Remove the temporary `PORTFOLIO_BASE_URL` override; redeploy and verify canonical navigation/feed URLs.
- [ ] Verify portfolio.dark.ca fully before switching the older hostname.
- [ ] Add `speaking.dark.ca` as a Pages custom domain and replace its Noti.st DNS target using the Pages-provided configuration.
- [ ] Add the single host redirect from `deploy/hostname-redirect-rule.json` to the zone's existing rules (do not replace the ruleset). Preserve path and query string.
- [ ] Codex: verify HTTPS, canonical URLs, old presentation/slide paths and query preservation on both domains; check for redirect loops.

portfolio.dark.ca is Active with SSL enabled. The served page still declares portfolio-dark-ca.pages.dev as canonical and uses it for navigation. Next remove the production `PORTFOLIO_BASE_URL` override and redeploy. Daniel fixed the GitHub repository access and the warning disappeared; a fresh push will test automatic deployment. Do not change speaking.dark.ca yet.

## 6. Routine publishing and rollback — both

- [ ] Exercise draft announcement -> preview -> PDF attachment -> assets commit/push -> portfolio commit/push -> hosted result. Use an isolated test branch/project for synthetic content; publish real content only when Daniel intends it to be public.
- [x] Resolve the disconnected-account banner: Daniel added portfolio.dark.ca to the existing GitHub App repository access; the warning disappeared. Automatic push-triggered deployment is checked separately below.
- [ ] Confirm a normal Git push triggers Pages deployment and that its build uses the pinned assets commit.
  - Daniel pushed real upcoming-talk publication `89f8bcd` successfully. Cloudflare initially stayed on `2fe31b6` while repository access was missing. Access is now fixed; push the pending launch-progress documentation to test a fresh event and include the Portugal change. Do not create a duplicate talk or reprocess any slides.
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
