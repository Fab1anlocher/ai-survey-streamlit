
-- Referenzschema (SQLite)
CREATE TABLE IF NOT EXISTS responses (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    alter_group TEXT,
    geschlecht TEXT,
    bildung TEXT,
    richtung TEXT,
    einkommen TEXT,
    prompt TEXT,
    image_b64 TEXT,
    gefallen INTEGER,
    ueberzeugung INTEGER,
    kommentar TEXT,
    extras_json JSON
);
