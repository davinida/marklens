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

function developmentBypassEnabled(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    process.env.MARKLENS_TURNSTILE_DEV_BYPASS === "1"
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
