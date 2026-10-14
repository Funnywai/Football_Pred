import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

const root = dirname(fileURLToPath(import.meta.url));

// The dashboard is a read-only consumer of the FastAPI app. All API access happens
// server-side (see lib/api.ts); the browser never talks to the API, so no CORS and no
// client-side token handling is needed. `output: "standalone"` keeps the production
// image small (only the files the server actually needs).
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  turbopack: { root },
};

export default nextConfig;
