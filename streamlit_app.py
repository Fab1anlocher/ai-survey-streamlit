import streamlit as st
import base64
import requests
import sqlite3
import uuid
import json
from datetime import datetime

st.set_page_config(page_title="Visuelles Präferenz-Experiment (neutral)", page_icon="🧪", layout="centered")

OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY")

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

        st.markdown("---")
        st.markdown("**Bild-/Stil-Präferenzen (neutral):**")
        motivthema = st.selectbox("Neutrales Motiv-Thema", [
            "Community-Event im Stadtpark",
            "Neues Schulgebäude (Architektur-Visual)",
            "Öffentlicher Platz / Begegnungszone",
            "Rathaus-Foyer / Informationsstand",
            "Neutraler Natur-Ort (Wiese/Bäume/See)"
        ])
        bildstil = st.selectbox("Bildstil", ["Fotorealistisch","Illustriert (clean)","Halbrealistisch"])
        realismus = st.slider("Realismusgrad", 1, 7, 6)
        tageszeit = st.selectbox("Tageszeit", ["Morgen","Mittag","Nachmittag","Abend","Blaue Stunde"])
        wetter = st.selectbox("Licht/Wetter", ["Sonnig weich","Bewölkt weich","Leichtes Gegenlicht","Innenraum soft light"])
        farbpalette = st.selectbox("Farbwelt", ["Neutral/Beige","Kühl/Blau","Warm/Orange","Grün/Natur","Monochrom"])
        stimmung = st.selectbox("Stimmung", ["Ruhig","Optimistisch","Seriös","Einladend"])
        personenanzahl = st.selectbox("Personenanzahl im Bild", ["1 Person","2–3 Personen","Gruppe (5–8)","Keine Person (nur Ort)"])
        bekleidung = st.selectbox("Bekleidungs-Vibe (falls Personen)", ["Casual","Smart-Casual","Business-leicht","Neutral/Outdoor"])
        komposition = st.selectbox("Komposition / Kamera", ["Halbtotal","Total/Weitwinkel","Porträt","Subjekt vorn, Ort hinten"])
        tiefe = st.selectbox("Tiefenwirkung", ["Leichte Tiefenunschärfe","Alles scharf (f/8+)","Moderate Unschärfe"])
        diversity = st.selectbox("Diversität (falls Personen)", ["Keine Präferenz","Leicht gemischt","Deutlich gemischt"])

        submitted = st.form_submit_button("Weiter →")

    if submitted:
        st.session_state.answers = dict(
            alter_group=alter_group, geschlecht=geschlecht, bildung=bildung, einkommen=einkommen,
            richtung="neutral",
            extras=dict(
                motivthema=motivthema, bildstil=bildstil, realismus=realismus, tageszeit=tageszeit,
                wetter=wetter, farbpalette=farbpalette, stimmung=stimmung, personenanzahl=personenanzahl,
                bekleidung=bekleidung, komposition=komposition, tiefe=tiefe, diversity=diversity
            ),
        )
        st.session_state.step = 2
        st.rerun()

# Step 2
if st.session_state.step == 2:
    st.info("Einen Moment, Motiv wird generiert …")
    a, e = st.session_state.answers, st.session_state.answers["extras"]
    base_prompt = (
        "Erzeuge ein 1080x1350 neutrales, nicht-persuasives Bild **ohne Text** und **ohne Logos**. "
        "Motivthema: {motivthema}. "
        "Falls Personen: realistische Darstellung passend zu Alter {alter_group}, Geschlecht {geschlecht}. "
        "Kleidung: {bekleidung}. Diversität: {diversity}. "
        "Stil: {bildstil}, Realismusgrad {realismus}/7. Stimmung: {stimmung}. Farbwelt: {farbpalette}. "
        "Komposition/Kamera: {komposition}. Tiefenwirkung: {tiefe}. "
        "Tageszeit: {tageszeit}, Licht/Wetter: {wetter}. "
        "Sozioökonomische Anmutung: {einkommen} (nur subtile Kontexte; nicht stereotypisieren). "
        "Keine politischen Inhalte oder Symbole."
    )
    prompt = base_prompt.format(
        motivthema=e["motivthema"], alter_group=a["alter_group"], geschlecht=a["geschlecht"],
        bekleidung=e["bekleidung"], diversity=e["diversity"], bildstil=e["bildstil"],
        realismus=e["realismus"], stimmung=e["stimmung"], farbpalette=e["farbpalette"],
        komposition=e["komposition"], tiefe=e["tiefe"], tageszeit=e["tageszeit"],
        wetter=e["wetter"], einkommen=a["einkommen"],
    )
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
