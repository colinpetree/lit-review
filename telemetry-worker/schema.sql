-- Apply once: wrangler d1 execute lit-review-census --remote --file=schema.sql
CREATE TABLE IF NOT EXISTS pings (
  day TEXT NOT NULL,        -- UTC date the service received it
  event TEXT NOT NULL,      -- 'daily' or 'new_install'
  version TEXT NOT NULL,
  platform TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (day, event, version, platform)
);

-- Versions confirmed to be published releases (filled on a version's first ping).
CREATE TABLE IF NOT EXISTS versions (
  version TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS downloads (
  day TEXT NOT NULL,        -- the day of the snapshot
  tag TEXT NOT NULL,        -- release tag, for example v1.2.3
  asset TEXT NOT NULL,      -- file name in the release
  downloads INTEGER NOT NULL,  -- GitHub's running total for that file on that day
  PRIMARY KEY (day, tag, asset)
);
