import {
  parseNameCheckResponse,
  SearchResponseSchema,
  type NameCheckResult,
  type SearchResponse,
} from "@/lib/contracts";

export type {
  GradeCode,
  SearchMatch,
  SearchResponse,
  StatusCode,
} from "@/lib/contracts";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public requestId: string | null = null,
    public retryAfter: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const STATUS_FALLBACK: Record<number, string> = {
  400: "요청 내용을 확인해 주세요.",
  401: "요청을 인증하지 못했어요. 새로고침 후 다시 시도해 주세요.",
  403: "자동 요청 확인에 실패했어요. 잠시 후 다시 시도해 주세요.",
  413: "파일이 너무 커요. 10MB 이하로 올려주세요.",
  415: "지원하지 않는 형식이에요. PNG·JPG·WEBP만 올릴 수 있어요.",
  422: "요청 값이 올바르지 않아요.",
  429: "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
  502: "검색 서비스의 응답을 확인할 수 없어요.",
  503: "검색 서비스가 아직 준비 중이에요. 잠시 후 다시 시도해 주세요.",
  504: "검색 시간이 너무 오래 걸렸어요. 다시 시도해 주세요.",
};

async function readBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function assertOk(response: Response): Promise<unknown> {
  const body = await readBody(response);
  if (response.ok) return body;

  const detail =
    body &&
    typeof body === "object" &&
    "detail" in body &&
    typeof body.detail === "string"
      ? body.detail
      : STATUS_FALLBACK[response.status] || "알 수 없는 오류가 발생했어요.";

  throw new ApiError(
    response.status,
    detail,
    response.headers.get("x-request-id"),
    response.headers.get("retry-after"),
  );
}

function networkError(error: unknown): never {
  if (error instanceof DOMException && error.name === "AbortError") throw error;
  throw new ApiError(0, "서버에 연결할 수 없어요. 네트워크 연결을 확인해 주세요.");
}

export async function searchTrademark(
  file: File,
  topK: number,
  turnstileToken: string,
  signal?: AbortSignal,
): Promise<SearchResponse> {
  const form = new FormData();
  form.append("file", file);

  let response: Response;
  try {
    response = await fetch(`/api/search?top_k=${topK}`, {
      method: "POST",
      headers: { "x-turnstile-token": turnstileToken },
      body: form,
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    networkError(error);
  }

  const body = await assertOk(response);
  const parsed = SearchResponseSchema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError(
      502,
      "검색 서비스의 응답 형식이 예상과 달라 결과를 표시할 수 없어요.",
      response.headers.get("x-request-id"),
    );
  }
  return parsed.data;
}

export async function checkTrademarkName(
  name: string,
  turnstileToken: string,
  signal?: AbortSignal,
): Promise<NameCheckResult> {
  let response: Response;
  try {
    response = await fetch("/api/name-check", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, turnstileToken }),
      credentials: "same-origin",
      cache: "no-store",
      signal,
    });
  } catch (error) {
    networkError(error);
  }

  const body = await assertOk(response);
  try {
    return parseNameCheckResponse(body, name);
  } catch {
    throw new ApiError(
      502,
      "이름 확인 서비스의 응답 형식이 예상과 달라 결과를 표시할 수 없어요.",
      response.headers.get("x-request-id"),
    );
  }
}

const SAFE_IMAGE_SEGMENT = /^[\p{L}\p{N} ._-]+$/u;

function bffImageUrl(pathname: string): string | null {
  if (!pathname.startsWith("/images/")) return null;
  try {
    const parts = pathname
      .slice("/images/".length)
      .split("/")
      .map((part) => decodeURIComponent(part));
    if (
      parts.some(
        (part) =>
          !part ||
          part === "." ||
          part === ".." ||
          !SAFE_IMAGE_SEGMENT.test(part),
      )
    ) {
      return null;
    }
    return `/api/images/${parts.map(encodeURIComponent).join("/")}`;
  } catch {
    return null;
  }
}

export function imageUrl(value?: string | null): string | null {
  const raw = value?.trim();
  if (!raw || raw.startsWith("//")) return null;

  try {
    const url = raw.startsWith("/images/")
      ? new URL(raw, "http://marklens.invalid")
      : new URL(raw);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password
    ) {
      return null;
    }
    return bffImageUrl(url.pathname);
  } catch {
    return null;
  }
}
