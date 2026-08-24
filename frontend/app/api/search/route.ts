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

const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
const MAX_MULTIPART_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024;

export async function POST(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  const contentLength = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_MULTIPART_BYTES) {
    return jsonError(413, "파일이 너무 커요. 10MB 이하로 올려주세요.", requestId);
  }

  const topK = Number(new URL(request.url).searchParams.get("top_k") || "5");
  if (!Number.isInteger(topK) || topK < 1 || topK > 20) {
    return jsonError(422, "결과 개수는 1개에서 20개 사이여야 해요.", requestId);
  }

  try {
    await verifyTurnstile(request.headers.get("x-turnstile-token"), request.headers);
  } catch (error) {
    return turnstileErrorResponse(error, requestId) ?? upstreamFailure(error, requestId);
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return jsonError(400, "업로드 요청을 읽을 수 없어요.", requestId);
  }

  const file = form.get("file");
  if (!(file instanceof File) || file.size === 0) {
    return jsonError(400, "분석할 이미지 파일을 선택해 주세요.", requestId);
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return jsonError(413, "파일이 너무 커요. 10MB 이하로 올려주세요.", requestId);
  }
  if (!ALLOWED_TYPES.has(file.type)) {
    return jsonError(415, "PNG, JPG, WEBP 이미지만 올릴 수 있어요.", requestId);
  }

  const upstreamForm = new FormData();
  upstreamForm.append("file", file, file.name);

  try {
    const config = getBackendConfig();
    const upstream = await fetch(`${config.baseUrl}/search?top_k=${topK}`, {
      method: "POST",
      headers: backendHeaders(config, requestId),
      body: upstreamForm,
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
