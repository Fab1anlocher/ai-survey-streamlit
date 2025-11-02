import streamlit as st
import base64
import requests
import sqlite3
import uuid
import json
from datetime import datetime
import os

st.set_page_config(page_title="Visuelles Präferenz-Experiment (neutral)", page_icon="🧪", layout="centered")


# Sicheres Lesen von Secrets: st.secrets kann beim Fehlen von
# `.streamlit/secrets.toml` eine FileNotFoundError auslösen. Wir
# fangen das ab und nutzen als Fallback Umgebungsvariablen.
def _safe_secret(key: str, env_var: str | None = None):
    env_var = env_var or key
    try:
        # st.secrets.get kann intern versuchen, die secrets-Datei zu parsen
        # und dabei FileNotFoundError werfen — daher der Try/Except.
        val = st.secrets.get(key)
        if val is not None:
            return val
    except FileNotFoundError:
        pass
    return os.environ.get(env_var)


OPENAI_API_KEY=_safe_secret("OPENAI_API_KEY")
SUPABASE_URL=_safe_secret("SUPABASE_URL")
SUPABASE_KEY=_safe_secret("SUPABASE_KEY")

if not OPENAI_API_KEY:
    st.warning(
        "OPENAI_API_KEY ist nicht gesetzt. Lege `OPENAI_API_KEY` in `.streamlit/secrets.toml` oder als Umgebungsvariable `OPENAI_API_KEY` ab. \n"
        "Ohne Key funktioniert die Bildgenerierung nicht."
    )
# ---------- DB Layer: Supabase (persistente Cloud) ODER Fallback SQLite ----------
@st.cache_resource
def _get_sqlite_conn():
    conn = sqlite3.connect("survey.db", check_same_thread=False)
    conn.execute("""
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
            extras_json TEXT
        )
    """)
    return conn

@st.cache_resource
def _get_supabase_client():
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            # Supabase-Client import kann fehlschlagen, wenn die Dependency nicht installiert ist.
            from supabase import create_client
        except Exception as imp_err:
            # Zeige eine Warnung im UI, falle aber sauber auf SQLite zurück.
            st.warning(
                f"Supabase-Client konnte nicht importiert werden ({imp_err}).\n"
                "Supabase-Funktionalität ist deaktiviert — es wird auf lokale SQLite-Fallback umgeschaltet."
            )
            return None

        try:
            return create_client(SUPABASE_URL, SUPABASE_KEY)
        except Exception as conn_err:
            st.error(f"Verbindung zu Supabase fehlgeschlagen: {conn_err}")
            return None
    return None

SUPABASE = _get_supabase_client()
SQLITE = _get_sqlite_conn() if SUPABASE is None else None

def db_insert_response(row: dict):
    if SUPABASE is not None:
        # Supabase: Insert (robust handling for different client response shapes)
        try:
            res = SUPABASE.table("responses").insert(row).execute()
        except Exception as e:
            # Netzwerk/client-level error
            raise RuntimeError(f"Supabase insert failed: {e}")

        # Try various ways to detect an error on the response object/dict
        err = None
        try:
            err = getattr(res, "error", None)
        except Exception:
            err = None

        if err is None and isinstance(res, dict):
            err = res.get("error") or res.get("message")

        status = None
        try:
            status = getattr(res, "status_code", getattr(res, "status", None))
        except Exception:
            status = None

        if err or (isinstance(status, int) and status >= 400):
            # Try to collect useful debug info
            info = None
            try:
                info = getattr(res, "data", None) or (res.get("data") if isinstance(res, dict) else None)
            except Exception:
                info = None
            raise RuntimeError(f"Supabase insert error: {err or status} | {info}")
    else:
        # SQLite Fallback
        with SQLITE:
            SQLITE.execute("""
                INSERT INTO responses
                (id, created_at, alter_group, geschlecht, bildung, richtung, einkommen,
                 prompt, image_b64, gefallen, ueberzeugung, kommentar, extras_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"], row["created_at"], row["alter_group"], row["geschlecht"],
                row["bildung"], row["richtung"], row.get("einkommen"),
                row["prompt"], row["image_b64"], row["gefallen"], row["ueberzeugung"],
                row["kommentar"], row.get("extras_json","{}")
            ))


def db_fetch_recent(n=50):
    if SUPABASE is not None:
        try:
            res = SUPABASE.table("responses") \
                .select("id,created_at,alter_group,geschlecht,bildung,richtung,einkommen,gefallen,ueberzeugung") \
                .order("created_at", desc=True).limit(n).execute()
        except Exception as e:
            raise RuntimeError(f"Supabase query failed: {e}")

        # robust error detection
        err = None
        try:
            err = getattr(res, "error", None)
        except Exception:
            err = None

        if err is None and isinstance(res, dict):
            err = res.get("error") or res.get("message")

        status = None
        try:
            status = getattr(res, "status_code", getattr(res, "status", None))
        except Exception:
            status = None

        if err or (isinstance(status, int) and status >= 400):
            raise RuntimeError(f"Supabase query error: {err or status}")

        data = None
        try:
            data = getattr(res, "data", None)
        except Exception:
            data = None
        if data is None and isinstance(res, dict):
            data = res.get("data")

        return data or []
    else:
        cur = SQLITE.execute("""
            SELECT id, created_at, alter_group, geschlecht, bildung, richtung, einkommen, gefallen, ueberzeugung
            FROM responses ORDER BY created_at DESC LIMIT ?
        """, (n,))
        rows = cur.fetchall()
        # SQLite → Liste von Tupeln zu Dicts für einheitliche Anzeige
        cols = ["id","created_at","alter_group","geschlecht","bildung","richtung","einkommen","gefallen","ueberzeugung"]
        return [dict(zip(cols, r)) for r in rows]

# ---------- Image Gen ----------
def generate_image_b64(prompt: str, size: str = "1024x1024") -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY fehlt in st.secrets.")
    # Build headers explicitly (Content-Type + Accept) to avoid unexpected redirects
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {"model": "gpt-image-1", "prompt": prompt, "size": size}
    url = "https://api.openai.com/v1/images/generations"

    resp = requests.post(url, json=payload, headers=headers, timeout=90, allow_redirects=True)

    # If the request was redirected, some servers convert the method to GET which causes
    # an "Invalid method for URL (GET ...)" error on the API side. Detect and report that.
    try:
        final_method = resp.request.method
        final_url = resp.request.url
    except Exception:
        final_method = None
        final_url = None

    if resp.history and final_method and final_method.upper() != "POST":
        # Provide a clear error message so user can spot redirect/misconfiguration
        raise RuntimeError(
            f"Image generation request was redirected and the final request used method={final_method} to {final_url}. "
            "This often means the endpoint redirected (301/302) and changed POST→GET. "
            "Check the request URL, avoid HTTP->HTTPS redirects, and ensure the endpoint is correct. "
            f"Response history: {[ (r.status_code, r.headers.get('location')) for r in resp.history ]}. "
            f"Final status: {resp.status_code}, body: {resp.text[:1000]}"
        )

    # Handle HTTP errors with clearer messages (include JSON body if present)
    try:
        resp.raise_for_status()
    except requests.HTTPError as http_err:
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        raise RuntimeError(f"Image generation failed: {resp.status_code} {resp.reason} - {body}")

    j = None
    try:
        j = resp.json()
    except Exception as e:
        raise RuntimeError(f"Could not parse JSON response from image API: {e} - body: {resp.text[:1000]}")

    # Response shape may vary; attempt to extract base64 payload
    try:
        return j["data"][0]["b64_json"]
    except Exception:
        raise RuntimeError(f"Unexpected image response shape: {j}")

# ---------- UI ----------
st.title("🎯 Visuelles Präferenz-Experiment (neutral, ohne Text/Logos)")
if SUPABASE is None:
    st.warning("Persistenz: **SQLite (temporär)**. Für dauerhafte Speicherung setze SUPABASE_URL & SUPABASE_KEY in den Secrets.")

if "step" not in st.session_state: st.session_state.step = 1
if "answers" not in st.session_state: st.session_state.answers = {}
if "image_b64" not in st.session_state: st.session_state.image_b64 = None
if "prompt" not in st.session_state: st.session_state.prompt = ""

# Step 1
if st.session_state.step == 1:
    with st.form("profil_form"):
        st.markdown("**Profil (nur Darstellung, optional):**")
        alter_group = st.selectbox("Alter (geschätzt)", ["18-24","25-34","35-44","45-54","55+"])
        geschlecht = st.selectbox("Geschlecht", ["Mann","Frau","Divers"])
        bildung = st.selectbox("Höchster Abschluss", ["Sek II","Lehre","HF/FH","Uni/ETH","Andere"])
        einkommen = st.selectbox("Einkommen (Selbsteinschätzung)", ["0–20’000 CHF","20’000–80’000 CHF","80’000–150’000 CHF","150’000+ CHF"])
        richtung = st.selectbox("Politische Richtung", ["Links","Mitte-Links","Mitte","Mitte-Rechts","Rechts"])

        submitted = st.form_submit_button("Weiter →")

        if submitted:
            # Wir speichern nur die Profilfelder; Bild-/Stil-Präferenzen wurden entfernt.
            st.session_state.answers = dict(
                alter_group=alter_group,
                geschlecht=geschlecht,
                bildung=bildung,
                einkommen=einkommen,
                richtung=richtung,
                extras={},
            )
            st.session_state.step = 2
            st.rerun()

# Step 2
if st.session_state.step == 2:
    st.info("Einen Moment, Motiv wird generiert …")
    a = st.session_state.answers
    # Kürzerer, präziser Prompt (weniger Tokenkosten).
    # Hinweis: Wir fordern eine zentrierte Komposition mit 10% Rand, damit wichtige Inhalte nicht abgeschnitten werden.
    base_prompt = (
        "Politische Anzeige für den Bau einer neuen öffentlichen Schule in Burgdorf, Schweiz."
        "Überzeuge die Zielgruppe kurz von den Vorteilen des Projekts."
        "Motiv: stimmige, positive Alltagsszene; keine Text-Overlays oder Logos."
        "Komposition: zentriert, gesamte Szene sichtbar, mindestens 10% Freiraum an allen Rändern (nicht zuschneiden)."
        "Farben: natürlich, freundliche Beleuchtung."
    )
    prompt = base_prompt + f" Zielgruppe: Alter {a['alter_group']}, Geschlecht {a['geschlecht']}, Bildung {a['bildung']}, Einkommen {a['einkommen']}, politische Richtung {a['richtung']}."
    try:
        # Hinweis: Die aktuelle Image-API erlaubt nur bestimmte Größen (z.B. '1024x1024', '1024x1536', '1536x1024' oder 'auto').
        # 512x512 wird vom API nicht akzeptiert. Wir verwenden hier '1024x1024' (kleinste unterstützte quadratische Größe).
        image_b64 = generate_image_b64(prompt, size="1024x1024")
        st.session_state.image_b64 = image_b64
        st.session_state.prompt = prompt
        st.session_state.step = 3
        st.rerun()
    except Exception as ex:
        st.error(f"Bildgenerierung fehlgeschlagen: {ex}")

# Step 3
if st.session_state.step == 3 and st.session_state.image_b64:
    st.subheader("Generiertes neutrales Motiv (ohne Text/Logos)")
    st.image(base64.b64decode(st.session_state.image_b64), use_column_width=True)

    with st.form("feedback_form"):
        gefallen = st.slider("Wie gut gefällt dir das Motiv insgesamt?", 1, 7, 4)
        glaubwürdigkeit = st.slider("Wie glaubwürdig wirkt die Darstellung?", 1, 7, 4)
        kommentar = st.text_area("Kurzes Feedback (optional)")
        finish = st.form_submit_button("Abschließen ✅")

    if finish:
        row = {
            "id": str(uuid.uuid4()),
            "created_at": datetime.utcnow().isoformat(),
            "alter_group": st.session_state.answers["alter_group"],
            "geschlecht": st.session_state.answers["geschlecht"],
            "bildung": st.session_state.answers["bildung"],
            "richtung": "neutral",
            "einkommen": st.session_state.answers["einkommen"],
            "prompt": st.session_state.prompt,
            "image_b64": st.session_state.image_b64,
            "gefallen": int(gefallen),
            "ueberzeugung": int(glaubwürdigkeit),  # ASCII-safe column name
            "kommentar": kommentar.strip(),
            "extras_json": json.dumps(st.session_state.answers.get("extras", {}), ensure_ascii=False),
        }
        try:
            db_insert_response(row)
            st.success("Danke! Deine Antworten wurden gespeichert.")
            st.session_state.step = 4
            st.rerun()
        except Exception as e:
            st.error(f"Speichern fehlgeschlagen: {e}")

# Step 4
if st.session_state.get("step") == 4:
    st.write("Du kannst das Fenster schließen. Vielen Dank fürs Mitmachen!")
    with st.expander("Admin: Schnellansicht (letzte Einträge)"):
        try:
            rows = db_fetch_recent(50)
            if rows:
                st.dataframe(rows, use_container_width=True)
            else:
                st.write("Noch keine Einträge.")
        except Exception as e:
            st.error(f"Admin-Ansicht fehlgeschlagen: {e}")
