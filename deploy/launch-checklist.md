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

Hosted HTTP preflight on 2026-11-06 passed: 400 HTML routes, 119 sampled static assets, complete smallest/largest PDF downloads (0.19 / 72.70 MiB), temporary-host canonical/navigation URLs, legacy redirects and draft exclusion. Daniel subsequently validated the browser checks on 2026-11-06. The local receipt is `.portfolio/hosted-check.json` (ignored).

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

- [x] Homepage, appearance list, talk groupings, video list and biography return successfully on the test hostname; Daniel subsequently validated browser layout on 2026-11-06.
- [x] Slides advance with buttons/keyboard; all-slides transcript works. Daniel validated on 2026-11-06.
- [x] PDF downloads work, including a complete 72.70 MiB PDF matched to its SHA-256; image-only entries have no PDF button.
- [x] YouTube/Vimeo recordings load after clicking; external Watch links work. Daniel validated on 2026-11-06.
- [x] Resources, feedback, headshots, map pins and attribution are present. Daniel validated on 2026-11-06.
- [x] Review mobile layout and check browser console/network failures. Daniel validated on 2026-11-06.
- [x] Initial hosted test verified draft exclusion across pages/feed/sitemap/map and a 404 direct URL. Daniel has since intentionally published Portugal in `89f8bcd`; its hosted appearance has been verified after the Git integration repair.
- [x] Legacy presentation slug redirects work, for example `/QfIYtz/statements-about-stateless`.
- [x] Sampled legacy slide route preserves its slide fragment and lands on the Pages hostname.
- [x] Browser review: primary navigation, controls and recording actions stay on the intended destinations. Daniel validated on 2026-11-06.

## 5. Canonical domain and speaking.dark.ca cutover — Daniel, then Codex

- [x] Save public DNS answers before cutover in `.portfolio/dns-before-cutover.json`; speaking.dark.ca still reaches the old site, and portfolio.dark.ca does not yet resolve.
- [x] Daniel recorded the former speaking.dark.ca target as `inbound.noti.st`. His post-change DNS screenshot shows the new CNAME target `portfolio-dark-ca.pages.dev`, Proxied, TTL Auto. No additional speaking.dark.ca DNS records were reported; existing zone redirect rules have not been inspected.
- [x] Add `portfolio.dark.ca` through Pages, complete DNS setup and activate HTTPS. Daniel's dashboard shows Active/SSL enabled; Codex verified the served page with normal TLS certificate validation using the current public DNS address.
- [x] Remove the temporary `PORTFOLIO_BASE_URL` override and redeploy. The successful automatic deployment serves canonical/navigation URLs at https://portfolio.dark.ca; the Portugal event is present in the feed.
- [x] Verify portfolio.dark.ca fully before switching the older hostname. Daniel validated on 2026-11-06.
- [x] Add `speaking.dark.ca` as a Pages custom domain and replace its Noti.st DNS target using the Pages-provided configuration. Daniel's dashboard screenshot confirms Active / SSL enabled on 2026-11-06.
- [x] Add the single host redirect from `deploy/hostname-redirect-rule.json` to the zone's existing rules (do not replace the ruleset). Daniel deployed the 301 redirect on 2026-11-06; path and query preservation verified.
- [x] Codex: verify HTTPS, canonical URLs, old presentation/slide paths and query preservation on both domains; check for redirect loops. Ten HTTPS requests passed on 2026-11-06; legacy slide 3 redirects retain `#3` and both query parameters. Receipt: `.portfolio/hostname-cutover-check.json` (ignored).

portfolio.dark.ca is Active with SSL enabled. Source `65eb37d` deployed automatically after the GitHub access fix and now serves canonical/navigation links on portfolio.dark.ca. Portugal publication is verified. Daniel validated the production deployment and browser acceptance checks on 2026-11-06 after pushing `998ae42`. The speaking.dark.ca cutover is complete: Pages custom domain Active/SSL enabled, DNS Proxied to Pages, and permanent redirects verified on 2026-11-06.

## 6. Routine publishing and rollback — both

- [ ] Exercise draft announcement -> preview -> PDF attachment -> assets commit/push -> portfolio commit/push -> hosted result. Use an isolated test branch/project for synthetic content; publish real content only when Daniel intends it to be public.
- [x] Resolve the disconnected-account banner: Daniel added portfolio.dark.ca to the existing GitHub App repository access; the warning disappeared. Automatic push-triggered deployment is checked separately below.
- [x] Confirm a normal Git push triggers Pages deployment: documentation commit `65eb37d` started the Cloudflare Pages check automatically and completed successfully. It includes Portugal publication `89f8bcd`; assets remain pinned by the committed lock.
  - Daniel pushed real upcoming-talk publication `89f8bcd` successfully. Cloudflare initially stayed on `2fe31b6` while repository access was missing. After the repair, Codex pushed real progress documentation in `65eb37d`; it deployed automatically and Portugal is now served on the canonical domain without slides. No duplicate talk or PDF processing was needed.
- [x] Record the verified canonical production deployment: `c68ad739-b10c-4189-adb9-8c1920a686b0`, source `65eb37d4d93f62a0c0bdfed5b6b8bed5ff93b90d`, assets `0580c25a8274d473d7f6cca5eea53d783ee1e641`. Local HTTP/GitHub receipt: `.portfolio/automatic-deploy-check.json`.
- [ ] Confirm the Pages dashboard's rollback action is available for a previous successful production deployment. Preview deployments are not rollback targets.
- [x] Document that a source rollback restores its recorded assets revision in the root `README.md`; keep referenced assets commits reachable.

## 7. Documentation — Codex

- [x] Keep both READMEs focused on everyday use, clone/setup, publishing and the grouped asset layout.
- [x] Consolidate deployment settings and rollback instructions into the root `README.md`; keep cutover progress in this checklist.
- [x] Keep this file as the actual launch progress record; distinguish local tests from hosted acceptance checks.
- [x] Separate migration history/backup details from normal website maintenance.
- [x] Apply the README drafts approved by Daniel on 2026-11-06 to both repositories. Consolidate the portfolio's authoring and deployment guides into its README and remove those separate guides.
- [x] Revisit both READMEs for fitness and purpose after everyday use: [portfolio issue #2](https://github.com/phrawzty/portfolio.dark.ca/issues/2).

## 8. Migration and local cleanup — Daniel decides; Codex can execute

Do this after the hosted site and normal publishing work.

- [x] Daniel moved the migration material to cold storage and deleted local `assets.dark.ca/preservation/`, reported 2026-11-06. Codex confirmed the local directory is absent.
  - Codex verified all 2,313 local preservation files against the manifest before Daniel moved them. The cold-storage copy was handled by Daniel and was not independently verified by Codex. The manifest remains recoverable from assets Git history.
- [x] At Daniel's request, delete both obsolete assets Releases and their attachments: `portfolio-assets-v1` and `notist-migration-2026-11-05`. GitHub now lists no Releases; both Git tags are retained. Remove the unused restore script, manifest, migration notes and obsolete ignore entries.
- [x] Stop the local preview and remove disposable build/review caches after review. Completed 2026-11-06: port 1112 is free; generated builds, review images, task browser profiles and local uv cache removed. Verification receipts retained.
- [x] Re-measure disk usage with hard links counted across both repositories. After localhost cleanup on 2026-11-06: portfolio 28 MiB, assets 2.2 GiB, combined 2.3 GiB (`du -sch` across both roots). Assets were retained. After Daniel moved the migration backup to cold storage, totals were 28 MiB portfolio, 1.4 GiB assets, 1.5 GiB combined.

## References

- [Cloudflare Git integration](https://developers.cloudflare.com/pages/get-started/git-integration/)
- [Build image and version overrides](https://developers.cloudflare.com/pages/configuration/build-image/)
- [Pages custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/)
- [Pages rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/)
- [CARTO Basemaps key dashboard](https://dashboard.basemaps.carto.com/)
