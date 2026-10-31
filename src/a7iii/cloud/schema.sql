-- A7III Control Desk / cloud sync schema (roadmap packages/07).
-- Written in the common subset of SQLite and PostgreSQL. JSON is stored as TEXT.
-- The suite runs it on SQLite; on PostgreSQL/Supabase replace the
-- "INTEGER PRIMARY KEY" ids with "BIGSERIAL PRIMARY KEY" if you want server-side ids.

CREATE TABLE IF NOT EXISTS shoots (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL,
    notes       TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS takes (
    id            INTEGER PRIMARY KEY,
    uid           TEXT NOT NULL UNIQUE,          -- stable across machines: <camera serial>-<start epoch ms>
    shoot_id      INTEGER REFERENCES shoots(id),
    camera        TEXT NOT NULL,
    started_at    REAL NOT NULL,
    duration_s    REAL,
    start_tc      TEXT,
    preroll_s     REAL DEFAULT 0,
    settings_json TEXT NOT NULL,                 -- fps, shutter, ISO, gamma, EI, lens, f-number...
    rating        INTEGER DEFAULT 0,
    notes         TEXT DEFAULT '',
    media_path    TEXT,
    updated_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY,
    take_uid  TEXT,
    t         REAL NOT NULL,
    kind      TEXT NOT NULL,                     -- af_warning, flicker, clipping, marker...
    payload   TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS presets (
    name        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,                   -- picture_profile, shutter, desk_layout...
    body_json   TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS luts (
    name        TEXT PRIMARY KEY,
    size        INTEGER NOT NULL,
    sha256      TEXT NOT NULL,
    cube        TEXT NOT NULL,                   -- .cube file contents
    updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS nvram_backups (
    sha256      TEXT PRIMARY KEY,                -- the backup's own seal
    serial      TEXT NOT NULL,
    model       TEXT NOT NULL,
    body_json   TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_takes_updated ON takes(updated_at);
CREATE INDEX IF NOT EXISTS idx_events_take ON events(take_uid);
