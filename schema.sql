
-- Referenzschema (SQLite)
CREATE TABLE IF NOT EXISTS responses (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    alter_group TEXT,
    bildung TEXT,
    richtung TEXT,
    prompt TEXT,
    image_b64 TEXT,
    gefallen INTEGER,
    überzeugung INTEGER,
    kommentar TEXT
);
