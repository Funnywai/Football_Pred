import { NextResponse } from "next/server";

import { getJson } from "@/lib/api";
import type { LlmResearchRun } from "@/lib/llm-types";

export const dynamic = "force-dynamic";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Server-side proxy for a single LLM research run. The browser stays on the
 * Next origin; FastAPI is never reached directly and no credentials leak.
 */
export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
) {
  const { runId } = await context.params;

  if (!UUID_PATTERN.test(runId)) {
    return NextResponse.json({ error: "invalid run id" }, { status: 400 });
  }

  const result = await getJson<LlmResearchRun>(
    `/llm/research-runs/${encodeURIComponent(runId)}`,
    "object",
  );

  if (result.error) {
    return NextResponse.json({ error: result.error }, { status: 502 });
  }

  if (!result.data || !result.data.run_id) {
    return NextResponse.json({ error: "run not found" }, { status: 404 });
  }

  return NextResponse.json(result.data);
}
