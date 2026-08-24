import {
  backendHeaders,
  backendSignal,
  getBackendConfig,
  jsonError,
  upstreamFailure,
} from "@/lib/server/backend";
import { getRequestId, headersWithRequestId } from "@/lib/server/request-id";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SAFE_SEGMENT = /^[\p{L}\p{N} ._-]+$/u;

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const requestId = getRequestId(request.headers);
  const { path } = await context.params;
  if (
    !path.length ||
    path.some(
      (segment) =>
        segment === "." || segment === ".." || !SAFE_SEGMENT.test(segment),
    )
  ) {
    return jsonError(400, "이미지 경로가 올바르지 않아요.", requestId);
  }

  try {
    const config = getBackendConfig();
    const encodedPath = path.map(encodeURIComponent).join("/");
    const upstream = await fetch(`${config.baseUrl}/images/${encodedPath}`, {
      method: "GET",
      headers: backendHeaders(config, requestId),
      cache: "no-store",
      redirect: "error",
      signal: backendSignal(request.signal),
    });
    const contentType = upstream.headers.get("content-type") ?? "";
    if (upstream.ok && !contentType.toLowerCase().startsWith("image/")) {
      return jsonError(502, "이미지 응답 형식이 올바르지 않아요.", requestId);
    }

    const headers = headersWithRequestId(requestId, {
      "cache-control": upstream.ok
        ? "public, max-age=3600, stale-while-revalidate=86400"
        : "no-store",
      "content-type": contentType || "application/octet-stream",
      "x-content-type-options": "nosniff",
    });
    const length = upstream.headers.get("content-length");
    if (length) headers.set("content-length", length);

    return new Response(upstream.body, {
      status: upstream.status,
      headers,
    });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
