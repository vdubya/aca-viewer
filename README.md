# AI Criteria Assistant Viewer

A sample Streamlit implementation showcasing the ACA Viewer. The app uploads PDF, Word or UFGS XML SEC files and displays them with dynamic highlighting driven by Palantir pipelines.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

## Features

- Upload a document and view it directly in the browser
- Table of Contents extraction with clickable navigation
- Named Entity Recognition overlays with label filtering
- Saved search terms with fuzzy matching
- Compare two documents with a unified diff view
- Comment on selected text
- Admin view of saved searches and comments via `?admin=1`

## Run locally

1. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Launch the app:

   ```bash
   streamlit run streamlit_app.py
   ```

   Or run the package directly:

   ```bash
   python -m aca_viewer
   ```

## Environment variables

- `PALANTIR_BASE` – base URL for Palantir pipelines (default: `https://foundry.api.dod.mil`)
- `PALANTIR_TOKEN` – token used for Palantir API requests

```
$ python -m aca_viewer
```