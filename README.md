# 🎈 Blank app template

A simple Streamlit app that demonstrates the ACA Viewer.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://blank-app-template.streamlit.app/)

### How to run it on your own machine

1. Install the requirements

   ```
   $ pip install -r requirements.txt
   ```

2. Run the app

   ```
   $ streamlit run streamlit_app.py
   ```

The `streamlit_app.py` entry point simply calls the `aca_viewer` module's
`run()` function which contains the actual app implementation.  You can also
invoke it directly:

```
$ python -m aca_viewer
```
