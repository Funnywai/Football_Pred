# TOUCHLINE/LAB — paper football research terminal

Read-only Next.js dashboard for the new-method football paper-trading backend.
One server-rendered page, five anchored sections: **Overview · Predictions · Paper
Ledger · Calibration · Technical**.

- The browser never calls the backend API. All six requests happen on the server in
  `lib/api.ts`, using `API_BASE_URL` (default `http://api:8000`).
- Every endpoint is fetched in parallel and isolated: a failing or empty endpoint
  renders a scoped degraded/empty state instead of crashing the page.
- `dynamic = "force-dynamic"` — each request renders a fresh snapshot.

## Local development

```bash
cd web
cp .env.example .env.local
# .env.local must point at a reachable backend from your machine:
# API_BASE_URL=http://localhost:8000
npm ci
npm run dev
```

Open <http://localhost:3000>. The API must expose the read-only dashboard routes
below; without it the page still renders with degraded panels.

### Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Next dev server |
| `npm run build` | Production standalone build |
| `npm run start` | Serve the production build |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest unit tests for formatting/calibration helpers |
| `npm run lint` | ESLint (Next core-web-vitals + TypeScript) |

## Docker

The image is a multi-stage standalone build and runs as non-root on port 3000.

```bash
cd web
docker build -t touchline-lab .
docker run --rm -p 3000:3000 -e API_BASE_URL=http://host.docker.internal:8000 touchline-lab
```

`host.docker.internal` works on Docker Desktop. On a compose network, use the API
service name (e.g. `http://api:8000`). Do not add this app to
`docker-compose.yml` unless that is separately approved; the service block would be:

```yaml
web:
  build: ./web
  environment:
    API_BASE_URL: http://api:8000
  ports:
    - "3000:3000"
  depends_on:
    - api
```

## API contract consumed (read-only)

| Route | Panel |
| --- | --- |
| `GET /dashboard/overview` | Header health, KPI strip, fixtures, sources, latest calibration |
| `GET /dashboard/predictions?limit=50` | Predictions feed |
| `GET /dashboard/bets?limit=100` | Equity + bet ledger |
| `GET /dashboard/equity` | Equity curve |
| `GET /dashboard/calibration` | Models, strategies, metrics, reliability plots, weights |
| `GET /dashboard/technical` | Revision, DB/Redis, counts, source runs, decisions |

Decimal, UUID and datetime values are expected as JSON strings. Types live in
`lib/types.ts`; `lib/api.ts` validates only the top-level payload shape and leaves
field-level tolerance to the renderers.

The `calibration` field on metric rows is backend-defined. `lib/calibration.ts`
tolerantly reads arrays, `{ bins: [...] }` wrappers, and bucket-keyed objects, then
draws compact reliability plots. Missing bins fall back to the metrics table.

## Structure

```
web/
  app/
    globals.css        design tokens + full dashboard styling
    layout.tsx         metadata, dark viewport, skip link
    page.tsx           force-dynamic server page and section composition
    icon.svg
  components/          masthead, nav, sections, equity/reliability SVGs, UI primitives
  lib/                 API client (server-only), types, formatting, calibration parsing
  tests/               Vitest unit tests
  Dockerfile
  .env.example
```

## Design notes

A dark "research terminal" identity: warm off-white type on graph-paper black, one
amber accent, sharp 1px rules, mono tabular numbers, section indices and a tick ruler
under the masthead. No external fonts or images; no client-side JavaScript is needed
for any panel. Tables scroll horizontally on narrow screens, focus states are always
visible, motion is limited to one masthead/KPI entrance and respects
`prefers-reduced-motion`.
