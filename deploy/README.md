# Deployment and rollback

The [launch checklist](launch-checklist.md) is the progress record and dashboard handoff. No Cloudflare deployment is considered verified until its hosted checks pass.

## Cloudflare Pages configuration

Connect `phrawzty/portfolio.dark.ca`, branch `main`, to a Pages project with Git integration. Use repository root, framework preset **None**, build command `sh scripts/cloudflare-build.sh`, output directory `public`.

Set build environment variables:

| Variable | Value |
| --- | --- |
| `ZOLA_VERSION` | `0.23.6` |
| `PYTHON_VERSION` | `3.13.3` |
| `PORTFOLIO_BASE_URL` | `https://<actual-project>.pages.dev` until the custom domain is ready |

Use the exact Pages hostname Cloudflare assigns. Remove `PORTFOLIO_BASE_URL` at canonical cutover so the configured `https://portfolio.dark.ca` is used. You can also test a different host locally with `uv run portfolio build --base-url https://example.pages.dev`.

The build restores the pinned `assets.dark.ca` Git revision, verifies files, and generates `public/`. It does not process PDFs or use Noti.st. Public Git reads need no account tokens. PDFs remain normal Git files in the assets checkout; Pages serves slide images/headshots and links PDFs to the configured HTTP base URL.

## Domains and legacy links

Register custom domains through the Pages project's **Custom domains** screen before completing their DNS configuration. Start with `portfolio.dark.ca`; switch `speaking.dark.ca` after the new site passes acceptance checks. Save its existing DNS target/proxy settings first.

The build generates legacy path redirects. The hostname redirect is a zone Redirect Rule: `hostname-redirect-rule.json` contains one rule to append to the existing ruleset. It preserves path/query string and sends speaking.dark.ca to portfolio.dark.ca. Do not replace the zone's entire ruleset with that file.

Update website restrictions for the existing key in the [CARTO Basemaps dashboard](https://dashboard.basemaps.carto.com/). Keep existing allowed hosts, add the actual test hostname and portfolio.dark.ca, and verify tile responses and the visible map.

## Rollback

In the Pages deployment list, use **Rollback to this deployment** on a previous successful production deployment. Preview deployments are not rollback targets. Record the first known-good deployment during launch.

For a lasting source correction, revert the faulty portfolio commit and push. Each source revision records its assets commit in `data/assets-lock.json`; keep those assets commits reachable. No separate PDF reconstruction is required.

A pre-cutover failure needs no DNS change. If the speaking.dark.ca cutover itself fails, disable the new host redirect and restore the recorded previous DNS settings while diagnosing it. The retained Noti.st target is a temporary fallback, not the long-term rollback mechanism.

## References

- [Cloudflare Git integration](https://developers.cloudflare.com/pages/get-started/git-integration/)
- [Build image and version overrides](https://developers.cloudflare.com/pages/configuration/build-image/)
- [Custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/)
- [Rollbacks](https://developers.cloudflare.com/pages/configuration/rollbacks/)
