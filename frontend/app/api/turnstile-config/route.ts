import { getRequestId, headersWithRequestId } from "@/lib/server/request-id";
import {
  developmentBypassEnabled,
  getTurnstileSiteKey,
} from "@/lib/server/turnstile";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Turnstile 위젯의 런타임 설정.
 *
 * 사이트 키를 NEXT_PUBLIC_ 로 빌드 시점에 인라인하면, 빌드 후 키를 바꿔도 위젯이
 * 옛 키(또는 빈 값)로 렌더되어 "설정이 없어 검색을 시작할 수 없어요"처럼 보인다.
 * 요청 시점의 서버 env 를 돌려줘 재빌드 없이 키 교체·bypass 전환이 반영되게 한다.
 *
 * 키 해석과 bypass 판정은 lib/server/turnstile 의 헬퍼가 단일 소스다 — 검증
 * 경로(verifyTurnstile)와 조건이 갈라지지 않게 하려고 여기서 복제하지 않는다.
 */
export async function GET(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  return Response.json(
    { siteKey: getTurnstileSiteKey(), devBypass: developmentBypassEnabled() },
    { headers: headersWithRequestId(requestId, { "cache-control": "no-store" }) },
  );
}
