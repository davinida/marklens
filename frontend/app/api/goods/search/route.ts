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

/**
 * 상품↔유사군 변환표 검색 프록시 (프론트-6 지정상품 입력 UI용) → 백엔드 GET /goods/search.
 *
 * Turnstile 을 요구하지 않는다. 근거: (1) 읽기 전용 로컬 메모리 조회라 KIPRIS 쿼터·CPU 모델을
 * 쓰지 않고 (2) 개인정보·질의 저장이 없으며 (3) 자동완성이라 키 입력마다 호출되므로 1회용
 * 토큰을 요구하면 쓸 수 없다. 같은 부류의 읽기 전용 GET(/api/images, /api/health)도 토큰
 * 없이 프록시한다. 남용 방지는 백엔드 IP 한도(MARKLENS_GOODS_RATELIMIT, 기본 60/minute)와
 * gateway 한도가 맡는다. 검색어가 GET 쿼리에 실리지만 상품명이라 /name-check 의 상표명처럼
 * 보호할 값이 아니다.
 */
const QuerySchema = z.object({
  q: z.string().trim().min(1).max(50),
  limit: z.coerce.number().int().min(1).max(50).optional(),
  nice_class: z.coerce.number().int().min(1).max(45).optional(),
});

export async function GET(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  const params = new URL(request.url).searchParams;
  const parsed = QuerySchema.safeParse({
    q: params.get("q") ?? "",
    limit: params.get("limit") ?? undefined,
    nice_class: params.get("nice_class") ?? undefined,
  });
  if (!parsed.success) {
    return jsonError(
      422,
      "상품명 검색어는 1자에서 50자 사이로 입력해 주세요. (limit 1~50, nice_class 1~45)",
      requestId,
    );
  }

  const upstreamParams = new URLSearchParams({ q: parsed.data.q });
  if (parsed.data.limit !== undefined) {
    upstreamParams.set("limit", String(parsed.data.limit));
  }
  if (parsed.data.nice_class !== undefined) {
    upstreamParams.set("nice_class", String(parsed.data.nice_class));
  }

  try {
    const config = getBackendConfig();
    const upstream = await fetch(`${config.baseUrl}/goods/search?${upstreamParams}`, {
      method: "GET",
      headers: backendHeaders(config, requestId),
      cache: "no-store",
      redirect: "error",
      signal: backendSignal(request.signal),
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: safeResponseHeaders(upstream, requestId),
    });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
