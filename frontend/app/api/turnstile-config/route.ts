import { getRequestId, headersWithRequestId } from "@/lib/server/request-id";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Turnstile 위젯의 런타임 설정.
 *
 * 사이트 키를 NEXT_PUBLIC_ 로 빌드 시점에 인라인하면, 빌드 후 키를 바꿔도 위젯이
 * 옛 키(또는 빈 값)로 렌더되어 "설정이 없어 검색을 시작할 수 없어요"처럼 보인다.
 * 요청 시점의 서버 env 를 돌려줘 재빌드 없이 키 교체·bypass 전환이 반영되게 한다.
 * 사이트 키는 설계상 공개 값이라 노출해도 안전하다.
 */
export async function GET(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  const siteKey = (
    process.env.MARKLENS_TURNSTILE_SITE_KEY ??
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ??
    ""
  ).trim();
  const devBypass =
    process.env.NODE_ENV !== "production" &&
    process.env.MARKLENS_TURNSTILE_DEV_BYPASS === "1";
  return Response.json(
    { siteKey, devBypass },
    { headers: headersWithRequestId(requestId, { "cache-control": "no-store" }) },
  );
}
