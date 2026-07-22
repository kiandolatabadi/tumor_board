# Deploying the Tumor Board Panel

> **Read this first.** This app is **not** like a static site (e.g. GitHub Pages
> on its own). It has two halves that deploy to two different kinds of host:
>
> | Half | What it is | Where it can go |
> |---|---|---|
> | **Frontend** (`frontend/`) | Static files (HTML/JS/CSS) built by Vite | GitHub Pages, Vercel, Netlify — any static host |
> | **Backend** (`backend/`) | A Python server that calls the Claude API | Render, Railway, Fly.io, a VPS — a **server** host |
>
> **Why the backend can't go on GitHub Pages:** it runs Python, and it holds your
> `ANTHROPIC_API_KEY`. A static host can't run Python, and putting the key in
> browser code would expose it to everyone who opens the page. The key must live
> as a **server-side environment variable** — never in the repo, never shipped to
> the browser. This is the one real difference from a pure client-side project
> like pain-visualiser.

```
Browser ──► Frontend (static, GitHub Pages)
                │  fetch(VITE_API_BASE + "/board")
                ▼
            Backend (Render/Railway) ──► Claude API
                ▲
        ANTHROPIC_API_KEY lives here only (a dashboard env var)
```

---

## Part 1 — Backend on a server host (Render, free/low-cost)

Any host that runs a Python web process works; Render is the least-friction. Steps
are the same idea on Railway/Fly.

1. Push this repo to GitHub (the key stays out — `.env` is gitignored).
2. On [render.com](https://render.com): **New → Web Service**, connect the repo.
3. Configure the service:
   - **Root Directory:** `backend`
   - **Runtime:** Python 3 (needs 3.11+; this repo is tested on 3.12)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn app.panel.api:app --host 0.0.0.0 --port $PORT`
4. Add environment variables (Render dashboard → **Environment**):
   - `ANTHROPIC_API_KEY` = your key  ← **only place it lives online**
   - `PANEL_MODEL` = `claude-sonnet-5`
   - `FRONTEND_ORIGIN` = your deployed frontend URL (e.g. `https://kiandolatabadi.github.io`)
5. Deploy. You'll get a URL like `https://tumor-board.onrender.com`. Test it:
   `https://tumor-board.onrender.com/health` should return `{"status":"ok"}`.

> Free tiers sleep when idle, so the first request after a nap is slow — fine for
> a demo. The panel runs several model calls per case, so a run takes tens of
> seconds regardless.

## Part 2 — Frontend on GitHub Pages

The frontend is static once built. It needs to know the backend URL at build time
via `VITE_API_BASE`.

**Option A — build locally, publish `dist/`:**
```bash
cd frontend
VITE_API_BASE=https://tumor-board.onrender.com npm run build
# publish the dist/ folder to the gh-pages branch:
npx gh-pages -d dist        # (npm i -g gh-pages, or use npx)
```
Then in the GitHub repo: **Settings → Pages → Source: gh-pages branch**.

**Option B — GitHub Actions (auto-build on push).** Add `.github/workflows/pages.yml`
that runs the same build with `VITE_API_BASE` set as a repo variable, then deploys
`frontend/dist` with the official Pages action. (Ask and this can be generated.)

> **Base path gotcha:** GitHub Pages serves a project site under
> `/<repo-name>/`. If the app is at `kiandolatabadi.github.io/tumor_board/`, set
> Vite's `base` to `/tumor_board/` (in `vite.config.ts`, `base: "/tumor_board/"`).
> A user/organization site (`<user>.github.io`) needs no base.

## Part 3 — Connect the two

- Backend `FRONTEND_ORIGIN` must equal the frontend's URL, or the browser blocks
  the calls (CORS). Update it in the Render dashboard, redeploy.
- Frontend `VITE_API_BASE` must equal the backend's URL. It's baked in at build
  time, so rebuild/redeploy the frontend if the backend URL changes.

---

## Key-safety checklist (do not skip)

- ✅ `ANTHROPIC_API_KEY` only ever lives in: your local `backend/.env` (gitignored)
  and your server host's env-var dashboard.
- ✅ It is **never** in `VITE_API_BASE`, never in any `frontend/` file, never in a
  commit. The frontend only knows the backend's *URL*, never the key.
- ✅ Before any push: `git status` shows no `.env`. Verify with
  `git check-ignore backend/.env` (should print the path).
- ✅ If a key is ever committed by accident, rotate it immediately in the Anthropic
  console — removing it from a later commit does not un-leak it.

## Run it all locally (no deployment)

```bash
# backend
cd backend && python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add ANTHROPIC_API_KEY
uvicorn app.panel.api:app --reload --port 8000

# frontend (second terminal) — uses the Vite proxy, no VITE_API_BASE needed
cd frontend && npm install && npm run dev
# open http://localhost:5173
```
