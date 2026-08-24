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

const BodySchema = z.object({
  name: z.string().trim().min(1).max(100),
  turnstileToken: z.string().min(1).max(2048),
});

async function callBackend(
  name: string,
  request: Request,
  requestId: string,
): Promise<Response> {
  const config = getBackendConfig();
  const headers = backendHeaders(config, requestId, {
    "content-type": "application/json",
  });
  const post = await fetch(`${config.baseUrl}/name-check`, {
    method: "POST",
    headers,
    body: JSON.stringify({ name }),
    cache: "no-store",
    redirect: "error",
    signal: backendSignal(request.signal),
  });

  if (![404, 405].includes(post.status)) return post;

  return fetch(`${config.baseUrl}/name-check?name=${encodeURIComponent(name)}`, {
    method: "GET",
    headers: backendHeaders(config, requestId),
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
    const upstream = await callBackend(input.name, request, requestId);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: safeResponseHeaders(upstream, requestId),
    });
  } catch (error) {
    return upstreamFailure(error, requestId);
  }
}
