# Football_Pred Mission Control (`web`)

Read-only Next.js dashboard for the football betting model (sub-system D). It is a
sibling compose service that reads the existing FastAPI API **server-side only** — the
browser never calls the API, so no CORS is needed and no token or secret reaches the
client. The design contract is [`DESIGN.md`](./DESIGN.md).

This is the first increment (walking skeleton): the shared header renders live data with
graceful degradation, and both tabs render labelled placeholder shells for every section.
The real sections, charts and tables land in later increments.

## Local development

Run the API, then the dashboard against it:

```bash
# terminal 1 — the API (from the repo root)
uv run uvicorn app.api.main:create_app --factory --reload    # http://127.0.0.1:8000

# terminal 2 — the dashboard
cd web
npm install
API_BASE_URL=http://127.0.0.1:8000 npm run dev               # http://127.0.0.1:3000
```

`API_BASE_URL` defaults to `http://app:8000` (the compose service name). If the API is
unreachable the header still renders and shows an explicit unavailable/stale state.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Dev server on port 3000 |
| `npm run build` | Production build (`next build`) |
| `npm run start` | Serve the production build |
| `npm run lint` | ESLint (`eslint .`) |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest run |
| `npm run doctor` | react-doctor static scan (dev-only tooling) |

## Build and run as a compose service

The `web` service is defined in the repo-root `docker-compose.yml`. It publishes **no
host port** — the Cloudflare Tunnel reaches `web:3000` over the compose network.

```bash
# from the repo root
docker compose build web
docker compose up -d web
docker compose ps          # web running, app healthy
```

The image is multi-stage: `npm ci` -> `next build` -> a runtime stage that ships only the
standalone server output and runs as a non-root user on port 3000.

## Architecture notes

- **Server-side only.** `lib/api.ts` and `lib/ops.ts` import `server-only`, so importing
  them from a Client Component is a build error. All fetches happen in Server Components.
- **Graceful degradation.** The fetch wrapper never throws; a failed request becomes
  `{ ok: false }` and the header renders an unavailable/stale state. `npm run build` does
  not fail when the API is down (the dashboard routes are `force-dynamic`).
- **Design tokens.** Every colour, font size, spacing value and component pattern traces
  to a token in `DESIGN.md`, implemented as CSS custom properties in `app/globals.css`.
- **Dev-only tooling.** `react-grab` and `react-scan` are injected in `app/layout.tsx`
  behind `process.env.NODE_ENV === "development"`; `react-doctor` is a dev-only static
  scan. None reach the production bundle.
