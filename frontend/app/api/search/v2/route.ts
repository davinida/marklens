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
const GOODS_CODE = /^[GS][0-9]{4,6}$/;
const MARK_TYPES = new Set(["문자", "도형", "결합"]);

export async function POST(request: Request): Promise<Response> {
  const requestId = getRequestId(request.headers);
  const contentLength = Number(request.headers.get("content-length") || "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_MULTIPART_BYTES) {
    return jsonError(413, "파일이 너무 커요. 10MB 이하로 올려주세요.", requestId);
  }

  const topKValues = new URL(request.url).searchParams.getAll("top_k");
  const rawTopK = topKValues[0] ?? "5";
  const topK = Number(rawTopK);
  if (topKValues.length > 1 || !/^[0-9]+$/.test(rawTopK) || !Number.isInteger(topK) || topK < 1 || topK > 20) {
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

  if (form.getAll("image").length > 1) {
    return jsonError(422, "image는 한 번만 보낼 수 있어요.", requestId);
  }
  const image = form.get("image");
  if (image !== null) {
    if (!(image instanceof File)) {
      return jsonError(415, "PNG, JPG, WEBP 이미지만 올릴 수 있어요.", requestId);
    }
    if (image.size === 0) {
      return jsonError(400, "분석할 이미지 파일을 선택해 주세요.", requestId);
    }
    if (image.size > MAX_UPLOAD_BYTES) {
      return jsonError(413, "파일이 너무 커요. 10MB 이하로 올려주세요.", requestId);
    }
    if (!ALLOWED_TYPES.has(image.type)) {
      return jsonError(415, "PNG, JPG, WEBP 이미지만 올릴 수 있어요.", requestId);
    }
  }

  for (const field of ["name", "type_override"] as const) {
    if (form.getAll(field).length > 1) {
      return jsonError(422, `${field}는 한 번만 보낼 수 있어요.`, requestId);
    }
    if (form.get(field) instanceof File) {
      return jsonError(422, `${field}는 문자열이어야 해요.`, requestId);
    }
  }

  const name = (form.get("name") as string | null)?.trim() ?? "";
  if (Array.from(name).length > 100) {
    return jsonError(422, "상표명은 100자 이하로 입력해 주세요.", requestId);
  }

  const rawGoods = form.getAll("goods_codes");
  if (rawGoods.some((value) => typeof value !== "string")) {
    return jsonError(422, "goods_codes는 문자열이어야 해요.", requestId);
  }
  const goodsCodes = [...new Set(
    (rawGoods as string[])
      .flatMap((value) => value.split(","))
      .map((value) => value.trim().toUpperCase())
      .filter(Boolean),
  )];
  if (goodsCodes.length > 60 || goodsCodes.some((code) => !GOODS_CODE.test(code))) {
    return jsonError(422, "유사군 코드는 G 또는 S와 숫자 4~6자리로, 최대 60개까지 입력해 주세요.", requestId);
  }

  const typeOverride = form.get("type_override") as string | null;
  if (typeOverride !== null && !MARK_TYPES.has(typeOverride)) {
    return jsonError(422, "type_override는 문자·도형·결합 중 하나여야 해요.", requestId);
  }
  if (image === null && !name && goodsCodes.length === 0) {
    return jsonError(400, "image, name, goods_codes 중 하나는 있어야 합니다.", requestId);
  }

  // Rebuild the body so verification tokens and unvalidated fields never cross the BFF.
  const upstreamForm = new FormData();
  if (image instanceof File) upstreamForm.append("image", image, image.name);
  if (name) upstreamForm.append("name", name);
  for (const code of goodsCodes) upstreamForm.append("goods_codes", code);
  if (typeOverride !== null) upstreamForm.append("type_override", typeOverride);

  try {
    const config = getBackendConfig();
    const upstream = await fetch(`${config.baseUrl}/search/v2?top_k=${topK}`, {
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
