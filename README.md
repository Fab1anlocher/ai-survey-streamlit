
# Streamlit Image Survey Starter

Schneller Starter für deinen **Option-B**-Flow:
- Umfrage (Profilfragen) →
- Bildgenerierung via OpenAI Images API →
- Bildanzeige →
- Follow-up-Fragen →
- Speicherung in SQLite

## 1) Lokal starten

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Lege deinen OpenAI Key in `.streamlit/secrets.toml` ab:

```toml
# .streamlit/secrets.toml
OPENAI_API_KEY = "sk-..."
```

Alternativ kannst du für lokale Entwicklung die Umgebungsvariable `OPENAI_API_KEY` setzen (z.B. in Bash):

```bash
# Bash (temporär für die Session)
export OPENAI_API_KEY="sk-..."

# oder dauerhaft in ~/.bashrc / ~/.profile
```

Die App prüft zuerst `st.secrets`, fällt bei Fehlen aber auf die Umgebungsvariable `OPENAI_API_KEY` zurück. Dadurch startet die App lokal auch, wenn keine `.streamlit/secrets.toml` vorhanden ist.

## 2) Deploy auf Streamlit Community Cloud

1. Erstelle ein GitHub-Repo und pushe diese Dateien.
2. Gehe auf https://share.streamlit.io, wähle dein Repo aus.
3. Unter **Settings → Secrets** füge hinzu:
   - `OPENAI_API_KEY` (Wert: dein API-Key)
4. App starten. Öffentliche URL teilen.

**Hinweis zu SQLite**: Die DB-Datei `survey.db` liegt im App-Verzeichnis. Auf der Community Cloud ist die Persistenz best-effort (Container-Restarts können Daten löschen). Für Produktion nutze z. B. **Supabase/Postgres** oder **Google Sheets**.

## 3) Optional: Externe Persistenz (kurz skizziert)

- **Supabase (Postgres)**: Nutze `supabase-py` oder REST. Lege eine Tabelle `responses` an (Schema analog).
- **Google Sheets**: Via `gspread` + Service Account; schreibe pro Response eine neue Zeile.

## 4) Datenschutz / Forschungspraxis

- Informiere Teilnehmer über Zweck, Verantwortliche, Speicherdauer, Widerruf.
- Keine Felder für sensible Daten.
- Pro Response eine **UUID**, kein Klarname.
- Prompt + Modellversion dokumentieren (bereits enthalten).
- Wenn du Bilddateien extern speicherst, nutze **nicht-öffentliche Buckets** + signierte URLs.

Viel Erfolg!
