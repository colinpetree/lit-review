# Counting service

The small Cloudflare Worker that receives Lit Review's anonymous counts (`backend/telemetry.py`)
and keeps GitHub's download counts over time. It is for the maintainer; it is not part of the app.

What it keeps: per day, event (`daily` or `new_install`), version and system type, with a count.
No IP, no user agent, no ID. Worker logging is off in `wrangler.toml`.

## One-time setup (needs `npm i -g wrangler` and `wrangler login`)
1. `wrangler d1 create lit-review-census`, then put the printed `database_id` in `wrangler.toml`.
2. `wrangler d1 execute lit-review-census --remote --file=schema.sql`
3. `wrangler.toml` already routes the Worker to `litreview-data.colinpetree.com`, which must be in a
   zone of the Cloudflare account you are logged in to.
4. `wrangler deploy`. Optional but advisable: a fine-grained GitHub token with no permissions (public
   data only) as a Worker secret, `wrangler secret put GITHUB_TOKEN`, so checking a new version's
   release is not held up by GitHub's shared anonymous limit.
5. In the Cloudflare dashboard, add a rate limiting rule for that hostname (for example 20
   requests per minute per IP, block). Cloudflare handles the IP for this; the Worker never stores it.
6. `ENDPOINT` in `backend/telemetry.py` already names that hostname. Until step 4 is done, copies
   built from this code fail to send, quietly. The Worker also refuses a version that is not a real
   release. A version is counted only if it is a published (not draft) GitHub release `v<version>`; the
   Worker checks on a version's first ping and remembers it, so publish the release before
   copies of it run. An unreachable GitHub answers 503 and the app retries later.

## Reading the numbers
`queries.sql` has the saved queries. Run them in the D1 console in the dashboard or with
`wrangler d1 execute lit-review-census --remote --command "..."`.

## Switching it off
Set the Worker variable `KILL` to `1`. It answers 410 and every installed copy stops sending for good.

## What the numbers mean
- Daily users: copies that were running that day (the app is a tray program, so a copy left open counts). A copy opened for less than a few seconds never reports.
- New installs: counted from the first release that has counting; a fresh data folder is a new install, an upgrade or a reinstall over existing data is not. A new Windows account counts as new.
- Downloads: GitHub's count per file, snapshotted daily. The zips are also fetched by the in-app updater, so for fresh installs use the `.dmg` and `new_install`.
- A lost reply can count one extra, and anyone can send fake counts to a public address: treat the numbers as approximate and compare with the GitHub downloads.
- The GitHub download API is public; only the pings are private to you.

## Testing locally
`wrangler dev --local` runs it with a local D1 (apply `schema.sql` with `--local`). Run the app with
`LIT_REVIEW_TESTING=1` and `LIT_REVIEW_CENSUS_URL=http://127.0.0.1:8787/` to send there.
