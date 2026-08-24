import "server-only";

import { z } from "zod";
import { headersWithRequestId } from "@/lib/server/request-id";

const BackendUrlSchema = z
  .string()
  .url()
  .refine((value) => ["http:", "https:"].includes(new URL(value).protocol));

export interface BackendConfig {
  baseUrl: string;
  apiKey: string | null;
}

export function getBackendConfig(): BackendConfig {
  const configured = process.env.MARKLENS_BACKEND_URL?.trim();
  if (!configured && process.env.NODE_ENV === "production") {
    throw new Error("MARKLENS_BACKEND_URL is required in production");
  }

  const apiKey = process.env.MARKLENS_BACKEND_API_KEY?.trim() || null;
  if (!apiKey && process.env.NODE_ENV === "production") {
    throw new Error("MARKLENS_BACKEND_API_KEY is required in production");
  }

  const baseUrl = BackendUrlSchema.parse(configured || "http://127.0.0.1:8000");
  return {
    baseUrl: baseUrl.replace(/\/+$/, ""),
    apiKey,
  };
}

export function backendHeaders(
  config: BackendConfig,
  requestId: string,
  extra?: HeadersInit,
): Headers {
  const headers = headersWithRequestId(requestId, extra);
  if (config.apiKey) headers.set("X-API-Key", config.apiKey);
  return headers;
}

export function backendSignal(requestSignal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(30_000);
  return requestSignal ? AbortSignal.any([requestSignal, timeout]) : timeout;
}

export function safeResponseHeaders(
  upstream: Response,
  requestId: string,
): Headers {
  const headers = headersWithRequestId(requestId, {
    "cache-control": "no-store",
  });
  for (const name of [
    "content-type",
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
  ]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

export function jsonError(
  status: number,
  detail: string,
  requestId: string,
): Response {
  return Response.json(
    { detail },
    {
      status,
      headers: headersWithRequestId(requestId, { "cache-control": "no-store" }),
    },
  );
}

export function upstreamFailure(error: unknown, requestId: string): Response {
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return jsonError(504, "검색 서비스 응답 시간이 초과됐어요.", requestId);
  }
  if (error instanceof DOMException && error.name === "AbortError") {
    return jsonError(499, "요청이 취소됐어요.", requestId);
  }
  return jsonError(502, "검색 서비스에 연결할 수 없어요.", requestId);
}
