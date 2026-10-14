import "server-only";

import { apiGet, type ApiResult } from "./api";
import type { OpsData, OpsJobs, OpsLogs, OpsRuns, OpsStatus } from "./types";

// Fetchers for the read-only /ops/* surface (app/api/ops.py). Server-side only.

export const getOpsStatus = (): Promise<ApiResult<OpsStatus>> => apiGet("/ops/status");

export const getOpsJobs = (): Promise<ApiResult<OpsJobs>> => apiGet("/ops/jobs");

export const getOpsRuns = (limit = 50): Promise<ApiResult<OpsRuns>> =>
  apiGet(`/ops/runs?limit=${limit}`);

export const getOpsLogs = (limit = 100): Promise<ApiResult<OpsLogs>> =>
  apiGet(`/ops/logs?limit=${limit}`);

export const getOpsData = (): Promise<ApiResult<OpsData>> => apiGet("/ops/data");
