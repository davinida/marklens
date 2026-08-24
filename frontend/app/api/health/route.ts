import { z } from "zod";
import {
  backendHeaders,
  backendSignal,
  getBackendConfig,
  jsonError,
  safeResponseHeaders,
  upstreamFailure,
} from "@/lib/server/backend";
import { getRequestId } from "@/lib/server/request-id";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PublicHealthSchema = z.object({
  status: z.string().min(1).max(32),
  engine_ready: z.boolean(),
  index_size: z.number().int().nonnegative(),
  trademark_count: z.number().int().nonnegative(),
  artifact_generation_id: z.string().min(1).nullable(),
});

export async function GET(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);

  try {
    const config = getBackendConfig();
    const upstream = await fetch(`${config.baseUrl}/health`, {
      method: "GET",
      headers: backendHeaders(config, requestId),
      cache: "no-store",
      redirect: "error",
      signal: backendSignal(request.signal),
    });

    if (!upstream.ok) {
      return jsonError(
        upstream.status,
        "서비스 상태를 확인할 수 없어요.",
        requestId,
      );
    }

    const parsed = PublicHealthSchema.safeParse(await upstream.json());
    if (!parsed.success) {
      return jsonError(
        502,
        "서비스 상태 응답 형식이 올바르지 않아요.",
        requestId,
      );
    }

    const responseHeaders = safeResponseHeaders(upstream, requestId);
    responseHeaders.set("content-type", "application/json; charset=utf-8");
    return Response.json(parsed.data, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
