import {
  backendHeaders,
  backendSignal,
  getBackendConfig,
  safeResponseHeaders,
  upstreamFailure,
} from "@/lib/server/backend";
import { getRequestId } from "@/lib/server/request-id";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * NICE 45개 류 목록(명칭·변환표 항목 수) 프록시 → 백엔드 GET /goods/classes.
 * 읽기 전용 정적 데이터라 Turnstile 없이 프록시한다(근거는 goods/search/route.ts 주석).
 * 변환표 판이 바뀔 때만 달라지므로 성공 응답만 1시간 캐시를 허용한다.
 */
export async function GET(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);

  try {
    const config = getBackendConfig();
    const upstream = await fetch(`${config.baseUrl}/goods/classes`, {
      method: "GET",
      headers: backendHeaders(config, requestId),
      cache: "no-store",
      redirect: "error",
      signal: backendSignal(request.signal),
    });
    const headers = safeResponseHeaders(upstream, requestId);
    if (upstream.ok) headers.set("cache-control", "public, max-age=3600");
    return new Response(upstream.body, { status: upstream.status, headers });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
