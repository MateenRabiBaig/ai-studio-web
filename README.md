# AI Studio Web

A full-stack AI recipe assistant: React + Vite frontend, FastAPI backend with
pydantic-ai (Google Gemini), per-user accounts, and persistent conversation
history in SQLite.

## Features

- **Accounts** — email/password registration and login, JWT bearer tokens,
  PBKDF2-SHA256 password hashing (600k iterations, per-password salt), 7-day
  token expiry, logout.
- **Private conversations** — every conversation and message belongs to a
  user. All ownership checks happen in the database layer on the backend;
  mismatched access returns `404` so one user can never probe for another
  user's data.
- **History** — conversations persist across refreshes; the last active
  conversation is restored on login. Titles are auto-generated from the first
  message and can be renamed. Failed AI turns are never persisted.
- **Recipe preferences** — dietary preference, max cooking time, and servings
  are stored on the user account, sent with every AI request, and survive
  logout/login.
- **Rate limiting** — sliding-window limits on login (5/min/IP), registration
  (3/10min/IP), and chat (20/min/user), returning `429` with a retry hint.
- **Polished UI** — grey/white Geist design, login/register screens, toasts,
  loading and empty states, inline rename, delete confirmation, retry for
  failed messages, responsive mobile layout.

## Project layout

```
backend/
  main.py         FastAPI app: auth, conversations, chat, rate limits
  agent.py        pydantic-ai agent (Gemini) + recipe instructions
  db.py           SQLModel schema (User, Conversation, Message) + engine
  security.py     password hashing + JWT issue/verify
  ratelimit.py    in-memory sliding-window rate limiter
  requirements.txt / .env.example
src/
  api.ts          fetch wrapper: auth header, error mapping, 401 handling
  authContext.ts  auth context + useAuth hook
  auth.tsx        AuthProvider: session restore, login/register/logout
  AuthScreen.tsx  login/registration UI
  App.tsx         chat application shell
  App.css         design system
```

## Setup

### Backend

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip install -r requirements.txt
cp .env.example .env                        # then fill in GEMINI_API_KEY and JWT_SECRET
.venv/bin/python -m uvicorn main:app --reload --port 8000
```

Generate a JWT secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The SQLite database (`backend/ai_studio.db`) is created automatically on
first start — no migration tool is configured. Schema changes currently ship
as `SQLModel.metadata.create_all`, which adds missing tables but not missing
columns; if you change an existing table, delete the database file in
development, or adopt Alembic before any real deployment.

### Frontend

```bash
npm install
npm run dev
```

The dev server runs on `http://localhost:5173` and proxies `/api/*` to
`http://127.0.0.1:8000` (see `vite.config.ts`).

### Environment variables (backend/.env)

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | yes | Google AI API key for the recipe agent |
| `APP_ENV` | no | Use `production` to require an explicit `JWT_SECRET`; defaults to `development` |
| `JWT_SECRET` | required in production | Signs access tokens and must be stable across restarts/workers |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no | Token lifetime (default `10080` = 7 days) |

API keys live only in the backend `.env`; the frontend never sees them.

## API

All `/api/*` routes except `/api/auth/*` require
`Authorization: Bearer <token>`. Interactive docs are at
`http://127.0.0.1:8000/docs` when the backend is running.

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/auth/register` | `{email, password, name?}` → token + user. `409` if email taken |
| `POST` | `/api/auth/login` | `{email, password}` → token + user. `401` on bad credentials. Rate limited |
| `POST` | `/api/auth/logout` | Acknowledges; JWT logout is client-side (delete the token) |
| `GET` | `/api/me` | Current user incl. preferences and last active conversation |
| `PATCH` | `/api/me/preferences` | Any of `{dietary_preference, max_cook_time_minutes, servings}`; values validated |
| `GET` | `/api/conversations` | The caller's conversations, newest activity first |
| `POST` | `/api/conversations` | Create (`{title?}`, ≤120 chars) |
| `GET` | `/api/conversations/{id}/messages` | Full history; also sets it as last active. `404` if not owned |
| `PATCH` | `/api/conversations/{id}` | Rename (`{title}`) |
| `DELETE` | `/api/conversations/{id}` | Delete with messages |
| `POST` | `/api/chat` | `{conversation_id?, content}` (content ≤8000 chars, ≤20/min). Creates the conversation on the first message, uses stored preferences, replays at most 20 prior messages to the model, persists the turn only on success. `429` when rate limited, `502/504` on AI provider failure/timeout |
| `GET` | `/health` | Unauthenticated liveness check |

## Tests

Backend smoke tests cover authentication, protected routes, user ownership
isolation, persisted preferences, chat persistence, preference override
rejection, and rate limiting:

```bash
cd backend
.venv/bin/python test_api.py
```

Frontend checks:

```bash
npm run lint
npm run build
```

## Security notes

- Passwords are never stored in plain text (PBKDF2-SHA256, 600,000
  iterations, random 16-byte salt, constant-time comparison).
- Tokens are HS256 JWTs with `exp`; invalid/expired tokens return `401` and
  the frontend clears the session and returns to login.
- CORS is restricted to the dev frontend origins and `Authorization` /
  `Content-Type` headers only.
- Validation errors and AI failures return generic messages; real errors are
  logged server-side only.
- Rate limiting is **in-process and in-memory**: it resets on backend restart
  and is not shared across workers. For multi-worker or multi-instance
  deployments, replace `ratelimit.check` with a Redis-backed implementation
  (same signature) — call sites won't change.
- The unused AG-UI endpoint has been removed so the model cannot be called
  through an unauthenticated route.

## Deployment notes

- Build the frontend with `npm run build` (outputs `dist/`) and serve it from
  any static host/CDN; run the backend with
  `.venv/bin/python -m uvicorn main:app --port 8000` behind a reverse proxy
  that forwards `/api/*`.
- Update the CORS origins in `backend/main.py` to your real frontend origin.
- Set a strong `JWT_SECRET` in the environment (not just `.env`) so sessions
  survive restarts and multiple workers agree on signatures.
- SQLite stores all data in one file (`backend/ai_studio.db`) — put it on a
  persistent volume and back it up, or migrate to Postgres (SQLModel keeps
  the code portable) for multi-instance deployments.
- Do not commit `.env` or `ai_studio.db`; both are covered by `.gitignore`.
