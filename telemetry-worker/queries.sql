-- Run one at a time: wrangler d1 execute lit-review-census --remote --command "<query>"
-- or paste into the D1 console in the Cloudflare dashboard.

-- Daily users (copies that were running that day), last 30 days
SELECT day, SUM(count) AS daily_users FROM pings WHERE event = 'daily' GROUP BY day ORDER BY day DESC LIMIT 30;

-- Daily users by version
SELECT day, version, SUM(count) AS daily_users FROM pings WHERE event = 'daily' GROUP BY day, version ORDER BY day DESC, version DESC LIMIT 60;

-- New installs per week
SELECT strftime('%Y-%W', day) AS week, SUM(count) AS new_installs FROM pings WHERE event = 'new_install' GROUP BY week ORDER BY week DESC;

-- Total new installs counted so far, by version they started on
SELECT version, SUM(count) AS new_installs FROM pings WHERE event = 'new_install' GROUP BY version ORDER BY version DESC;

-- Downloads per file for each release (latest snapshot)
SELECT tag, asset, downloads FROM downloads WHERE day = (SELECT MAX(day) FROM downloads) ORDER BY tag DESC, asset;

-- Downloads per release (sum of the latest snapshot; zips include the in-app updater's downloads)
SELECT tag, SUM(downloads) AS downloads FROM downloads WHERE day = (SELECT MAX(day) FROM downloads) AND asset NOT LIKE 'update-manifest%' AND asset NOT LIKE 'SHA256%' GROUP BY tag ORDER BY tag DESC;
