# AI Criteria Assistant (ACA Viewer)

A Streamlit web application for viewing PDF, Word and XML documents with dynamic highlighting powered by Palantir data pipelines.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

## Features

- Upload a document and view extracted table of contents and named entities
- Toggle search terms with fuzzy matching and highlight results
- Compare two documents using a unified diff view
- Add comments on selected text
- Admin mode for reviewing saved searches and comments

## Running locally

1. Install the requirements

   ```bash
   pip install -r requirements.txt
   ```

2. Start the app

   ```bash
   streamlit run streamlit_app.py
   ```

   You may set `PALANTIR_BASE` and `PALANTIR_TOKEN` environment variables to enable the Palantir API pipelines.

You can also invoke the package directly:

```bash
python -m aca_viewer
```
