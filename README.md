# Distill Error Dashboard (Streamlit)

A user-friendly Streamlit dashboard that surfaces **Distill Monitor** errors, grouped and prioritized by **jurisdiction banding**.

This repo currently supports two modes:

1. **Distill Cloud (monitor.distill.io) scraping** (default): logs in using an exported Distill session (stored in Streamlit secrets) and pulls the “Error” lists for each watchlist.
2. **Local Distill Chromium artifacts** (optional): drop exports/logs into `data/` and point the app at that folder (parser stub included for extension).

## What you get

- KPI tiles: total errors, high/medium counts, fixable vs self-resolving
- Filters: compliance area, min banding, jurisdiction, error type, fixability
- Charts: errors by area & banding, top jurisdictions, error-type breakdown
- Detail table + CSV download

## Quickstart (local)

```bash
git clone https://github.com/cjenson97/distill-error-dashboard.git
cd distill-error-dashboard
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Distill session (for Cloud scraping)

This app expects a Distill session JSON string in Streamlit secrets:

- `.streamlit/secrets.toml` (not committed)

Example:

```toml
[distill]
session = "{...}"  # JSON string, exported storage_state from Playwright
```

The scraper uses Playwright and will run `playwright install chromium` automatically.

## Jurisdiction banding

Banding rules live in `banding.py`.

- Financial Services + Gambling Compliance use `fs`
- Payments Compliance uses `pc`
- Unknown jurisdictions default to `4. Lowest`

## Local Distill Chromium (optional)

If you have Distill Chromium downloaded locally and want to parse local outputs instead of scraping:

- Put sample files in `data/`
- Extend `local_distill.py` to parse your exports/logs
- Switch the app sidebar toggle to use local mode

## Deployment

This is Streamlit-ready.

- `requirements.txt` already includes `streamlit`, `playwright`, `pandas`, `plotly`
- `packages.txt` can be used by Streamlit Cloud for system deps
