# HireSignal Frontend

React + Vite dashboard for running HireSignal candidate evaluations.

## Features

- Upload multiple PDF/DOCX resumes.
- Add GitHub, LinkedIn, Twitter/X, email, and name overrides per candidate.
- Run multiple independent candidate sessions in parallel.
- Per-candidate progress, logs, warnings, and retry/reset controls.
- Ranked final reports with CSV/JSON export.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

By default the dashboard points to:

- API: `http://127.0.0.1:8000`
- API key: `dev-api-key-change-in-production`

You can change both in the dashboard UI. For environment defaults, copy:

```bash
cp .env.example .env.local
```

Then edit `.env.local`.

## How parallel sessions work

The browser starts one end-to-end pipeline per candidate:

1. `POST /api/v1/resume/score`
2. `POST /api/v1/social/analyze`
3. `POST /api/v1/candidate/evaluate`

The “Parallel sessions” number controls how many candidate pipelines run at the same time.
