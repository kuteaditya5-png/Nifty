# NIFTY AI — Vercel Deployment Package

This package contains the current NIFTY AI FastAPI dashboard prepared for Vercel.

## Included

- `app.py` — FastAPI application and dashboard
- `requirements.txt` — Python dependencies
- `pyproject.toml` — Python 3.14 selection and dependencies
- `vercel.json` — 60-second function-duration configuration
- `.env.example` — example local environment file
- `.gitignore` — prevents secrets/venv files from being committed

The production root `/` redirects to `/dashboard`.

## Main URLs

After deployment:

- `/` → dashboard
- `/dashboard` → visual NIFTY dashboard
- `/prediction` → combined prediction JSON
- `/option-chain` → NIFTY option-chain analysis
- `/candlestick-analysis` → candlestick-pattern analysis
- `/chart-data?interval=5m` → chart candles
- `/institutional-flow` → FII/FPI and DII
- `/global-analysis` → global-market cues
- `/health` → simple health check
- `/docs` → FastAPI Swagger UI

## 1. Test locally

Open PowerShell in this folder.

Create a virtual environment:

```powershell
python -m venv venv
```

If PowerShell blocks activation for the current window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Activate it:

```powershell
venv\Scripts\activate
```

Install packages:

```powershell
python -m pip install -r requirements.txt
```

Create your local `.env` file by copying `.env.example`, then put your real NewsAPI key in it:

```text
NEWS_API_KEY=your_real_key
```

Start the app:

```powershell
python -m uvicorn app:app --reload
```

Open:

```text
http://127.0.0.1:8000/dashboard
```

## 2. Put the project on GitHub

Create a new empty GitHub repository, for example `nifty-ai`.

From PowerShell in this project folder:

```powershell
git init
git add .
git commit -m "Initial NIFTY AI deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/nifty-ai.git
git push -u origin main
```

Do **not** add your real `.env` file. It is already excluded by `.gitignore`.

You can also upload the project files using GitHub's web interface instead of Git commands.

## 3. Deploy on Vercel

1. Sign in to Vercel.
2. Choose **Add New → Project**.
3. Import the GitHub repository containing this package.
4. Vercel should detect the FastAPI app from `app.py`; no custom build command is required.
5. Before/after the first deployment, open the project:
   **Settings → Environment Variables**.
6. Add:

```text
Name:  NEWS_API_KEY
Value: your_real_newsapi_key
```

Enable it for Production and Preview as needed.
7. Deploy/redeploy the project.

Environment-variable changes only affect new deployments, so redeploy after changing the key.

## 4. Test the live deployment

Open these URLs on your Vercel domain:

```text
/health
/dashboard
/chart-data?interval=5m
/institutional-flow
/option-chain
/candlestick-analysis
/prediction
```

If `/health` works but NSE endpoints fail, the application itself deployed correctly and NSE is likely rejecting/rate-limiting the cloud request.

## Important production notes

### NSE endpoints

The FII/DII and option-chain modules use NSE web endpoints with an NSE session/cookies. They work on the current local setup, but NSE can change or rate-limit these endpoints. Vercel deployment should be tested before relying on those values.

### Market-data freshness

`yfinance` is used for NIFTY, VIX and global-market data. Treat it as near-live/research data rather than exchange-grade tick-by-tick market data.

### Dashboard chart

The candlestick chart loads the Lightweight Charts browser bundle from a public CDN. The browser needs internet access to that CDN.

### Trading risk

The prediction engine is a heuristic decision-support model. Its displayed scenario probabilities are not proven historical accuracy until a proper backtest/prediction-history system is built.
