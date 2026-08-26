import "server-only";

import { z } from "zod";
import { headersWithRequestId } from "@/lib/server/request-id";
import { TURNSTILE_ACTION } from "@/lib/turnstile";

const VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const DEV_BYPASS_TOKEN = "dev-bypass";

const SiteverifySchema = z
  .object({
    success: z.boolean(),
    hostname: z.string().optional(),
    action: z.string().optional(),
    "error-codes": z.array(z.string()).optional(),
  })
  .passthrough();

export class TurnstileError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "TurnstileError";
  }
}

/**
 * 개발용 bypass 스위치. 검증(verifyTurnstile)과 위젯 런타임 설정
 * (/api/turnstile-config)이 같은 조건을 봐야 "위젯은 bypass인데 서버는 아님"
 * 같은 어긋남이 생기지 않는다 — 그래서 여기 한 곳에만 둔다.
 */
export function developmentBypassEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    process.env.MARKLENS_TURNSTILE_DEV_BYPASS === "1"
  );
}

/**
 * 위젯에 내려줄 Turnstile 사이트 키를 요청 시점에 해석한다. 사이트 키는 설계상
 * 공개 값이라 브라우저에 노출해도 안전하다.
 *
 * 서버 전용 MARKLENS_TURNSTILE_SITE_KEY 를 우선하고, 없으면 기존 로컬 셋업
 * 호환을 위해 NEXT_PUBLIC_TURNSTILE_SITE_KEY 로 폴백한다. `??` 가 아니라 trim 후
 * 빈 문자열을 "미설정"으로 취급하는 이유: `??` 는 빈 문자열을 '설정됨'으로 보기
 * 때문에, MARKLENS_ 키가 공란으로 존재하기만 해도 유효한 폴백이 영구히 무시된다.
 *
 * 주의: Docker standalone 빌드에서 NEXT_PUBLIC_* 은 빌드 시점에 값이 인라인된다.
 * 따라서 폴백 경로로는 "재빌드 없는 키 교체"가 되지 않는다. 런타임에 env 만
 * 바꿔서 키를 교체하려면 MARKLENS_TURNSTILE_SITE_KEY 를 쓰라.
 */
export function getTurnstileSiteKey(): string {
  return (
    process.env.MARKLENS_TURNSTILE_SITE_KEY?.trim() ||
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY?.trim() ||
    ""
  );
}

function clientIp(headers: Headers): string | null {
  const direct = headers.get("x-real-ip") || headers.get("cf-connecting-ip");
  if (direct) return direct.trim();
  return headers.get("x-forwarded-for")?.split(",")[0]?.trim() || null;
}

export async function verifyTurnstile(
  token: unknown,
  requestHeaders: Headers,
): Promise<void> {
  if (typeof token !== "string" || !token || token.length > 2048) {
    throw new TurnstileError(403, "자동 요청 확인을 완료해 주세요.");
  }

  if (developmentBypassEnabled() && token === DEV_BYPASS_TOKEN) return;

  const secret = process.env.MARKLENS_TURNSTILE_SECRET_KEY?.trim();
  if (!secret) {
    throw new TurnstileError(
      503,
      "자동 요청 확인 서비스가 설정되지 않았어요. 관리자에게 문의해 주세요.",
    );
  }

  const expectedHosts = (process.env.MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES ?? "")
    .split(",")
    .map((host) => host.trim().toLowerCase())
    .filter(Boolean);
  if (process.env.NODE_ENV === "production" && expectedHosts.length === 0) {
    throw new TurnstileError(
      503,
      "자동 요청 확인 호스트 설정이 없어 요청을 처리할 수 없어요.",
    );
  }

  const payload: Record<string, string> = {
    secret,
    response: token,
    idempotency_key: crypto.randomUUID(),
  };
  const ip = clientIp(requestHeaders);
  if (ip) payload.remoteip = ip;

  let response: Response;
  try {
    response = await fetch(VERIFY_URL, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
  } catch {
    throw new TurnstileError(
      503,
      "자동 요청 확인 서비스에 연결할 수 없어요. 잠시 후 다시 시도해 주세요.",
    );
  }

  let result: z.infer<typeof SiteverifySchema>;
  try {
    result = SiteverifySchema.parse(await response.json());
  } catch {
    throw new TurnstileError(503, "자동 요청 확인 응답을 처리할 수 없어요.");
  }

  const actionMatches = result.action === TURNSTILE_ACTION;
  const hostnameMatches =
    expectedHosts.length === 0 ||
    (result.hostname ? expectedHosts.includes(result.hostname.toLowerCase()) : false);

  if (!response.ok || !result.success || !actionMatches || !hostnameMatches) {
    throw new TurnstileError(
      403,
      "자동 요청 확인에 실패했어요. 확인을 새로 진행해 주세요.",
    );
  }
}

export function turnstileErrorResponse(
  error: unknown,
  requestId: string,
): Response | null {
  if (!(error instanceof TurnstileError)) return null;
  return Response.json(
    { detail: error.message },
    {
      status: error.status,
      headers: headersWithRequestId(requestId, { "cache-control": "no-store" }),
    },
  );
}
