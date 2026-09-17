import { z } from "zod";
import {
  backendHeaders,
  backendSignal,
  getBackendConfig,
  jsonError,
  safeResponseHeaders,
  upstreamFailure,
} from "@/lib/server/backend";
import {
  turnstileErrorResponse,
  verifyTurnstile,
} from "@/lib/server/turnstile";
import { getRequestId } from "@/lib/server/request-id";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// name-check 라우트와 같은 본문 계약. top_k 는 선택(미지정 시 백엔드 기본값).
const BodySchema = z.object({
  name: z.string().trim().min(1).max(100),
  turnstileToken: z.string().min(1).max(2048),
  top_k: z.number().int().min(1).max(20).optional(),
});

async function callBackend(
  input: { name: string; top_k?: number },
  request: Request,
  requestId: string,
): Promise<Response> {
  const config = getBackendConfig();
  const headers = backendHeaders(config, requestId, {
    "content-type": "application/json",
  });
  return fetch(`${config.baseUrl}/phonetic-search`, {
    method: "POST",
    headers,
    body: JSON.stringify(input),
    cache: "no-store",
    redirect: "error",
    signal: backendSignal(request.signal),
  });
}

export async function POST(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  let input: z.infer<typeof BodySchema>;
  try {
    input = BodySchema.parse(await request.json());
  } catch {
    return jsonError(422, "상표 이름을 1자에서 100자 사이로 입력해 주세요.", requestId);
  }

  try {
    await verifyTurnstile(input.turnstileToken, request.headers);
  } catch (error) {
    return turnstileErrorResponse(error, requestId) ?? upstreamFailure(error, requestId);
  }

  try {
    const upstream = await callBackend(
      input.top_k === undefined
        ? { name: input.name }
        : { name: input.name, top_k: input.top_k },
      request,
      requestId,
    );
    return new Response(upstream.body, {
      status: upstream.status,
      headers: safeResponseHeaders(upstream, requestId),
    });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
