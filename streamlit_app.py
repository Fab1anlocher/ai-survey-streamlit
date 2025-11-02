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


OPENAI_API_KEY = _safe_secret("OPENAI_API_KEY")
SUPABASE_URL = _safe_secret("SUPABASE_URL")
SUPABASE_KEY = _safe_secret("SUPABASE_KEY")

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
            überzeugung INTEGER,
            kommentar TEXT,
            extras_json TEXT
        )
    """)
    return conn

@st.cache_resource
def _get_supabase_client():
    if SUPABASE_URL and SUPABASE_KEY:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_KEY)
    return None

SUPABASE = _get_supabase_client()
SQLITE = _get_sqlite_conn() if SUPABASE is None else None

def db_insert_response(row: dict):
    if SUPABASE is not None:
        # Supabase: Insert
        res = SUPABASE.table("responses").insert(row).execute()
        if res.error:
            raise RuntimeError(str(res.error))
    else:
        # SQLite Fallback
        with SQLITE:
            SQLITE.execute("""
                INSERT INTO responses
                (id, created_at, alter_group, geschlecht, bildung, richtung, einkommen,
                 prompt, image_b64, gefallen, überzeugung, kommentar, extras_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["id"], row["created_at"], row["alter_group"], row["geschlecht"],
                row["bildung"], row["richtung"], row.get("einkommen"),
                row["prompt"], row["image_b64"], row["gefallen"], row["überzeugung"],
                row["kommentar"], row.get("extras_json","{}")
            ))

def db_fetch_recent(n=50):
    if SUPABASE is not None:
        res = SUPABASE.table("responses") \
            .select("id,created_at,alter_group,geschlecht,bildung,richtung,einkommen,gefallen,überzeugung") \
            .order("created_at", desc=True).limit(n).execute()
        if res.error:
            raise RuntimeError(str(res.error))
        return res.data or []
    else:
        cur = SQLITE.execute("""
            SELECT id, created_at, alter_group, geschlecht, bildung, richtung, einkommen, gefallen, überzeugung
            FROM responses ORDER BY created_at DESC LIMIT ?
        """, (n,))
        rows = cur.fetchall()
        # SQLite → Liste von Tupeln zu Dicts für einheitliche Anzeige
        cols = ["id","created_at","alter_group","geschlecht","bildung","richtung","einkommen","gefallen","überzeugung"]
        return [dict(zip(cols, r)) for r in rows]

# ---------- Image Gen ----------
def generate_image_b64(prompt: str, size: str = "1024x1024") -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY fehlt in st.secrets.")
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    payload = {"model": "gpt-image-1", "prompt": prompt, "size": size}
    resp = requests.post("https://api.openai.com/v1/images/generations", json=payload, headers=headers, timeout=90)
    resp.raise_for_status()
    return resp.json()["data"][0]["b64_json"]

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
    # Promt 
    base_prompt = (
        "Erzeuge eine politsche Werbung für Bau einer neuen öffentlichen Schule in Burgdorf, Schweiz."
        "Überzeugung der Zielgruppe von der Notwendigkeit/den Vorteilen des Projekts."
        "Zielgruppe für die Werbung: Alter:{alter_group} Geschlecht {geschlecht} bildung {bildung}, einkommen {einkommen}m richtung {richtung}. "
        "Natürliche Farben, neutraler Stil, keine politischen Inhalte oder Symbole."
    )
    prompt = base_prompt.format(alter_group=a["alter_group"], geschlecht=a["geschlecht"], bildung=a["bildung"], einkommen=a["einkommen"], richtung=a["richtung"]) 
    try:
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
            "überzeugung": int(glaubwürdigkeit),  # Feldname beibehalten
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
