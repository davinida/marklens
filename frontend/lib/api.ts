import {
  GoodsClassesResponseSchema,
  GoodsSearchResponseSchema,
  parseNameCheckResponse,
  PhoneticSearchResponseSchema,
  SearchResponseSchema,
  type GoodsClassesResponse,
  type GoodsSearchResponse,
  type NameCheckResult,
  type PhoneticSearchResponse,
  type SearchResponse,
} from "@/lib/contracts";

export type {
  GoodsClass,
  GoodsClassesResponse,
  GoodsMatch,
  GoodsSearchResponse,
  GradeCode,
  PhoneticMatch,
  PhoneticSearchResponse,
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

/** X1 호칭(발음) 유사도 검색 — 로컬 DB 상표명과 비교한 상위 후보. name-check 와 별개 호출. */
export async function searchPhonetic(
  name: string,
  turnstileToken: string,
  signal?: AbortSignal,
): Promise<PhoneticSearchResponse> {
  let response: Response;
  try {
    response = await fetch("/api/phonetic-search", {
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
  const parsed = PhoneticSearchResponseSchema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError(
      502,
      "발음 유사도 서비스의 응답 형식이 예상과 달라 결과를 표시할 수 없어요.",
      response.headers.get("x-request-id"),
    );
  }
  return parsed.data;
}

/**
 * 상품↔유사군 변환표 검색 (프론트-6 지정상품 입력). 정확 > 접두 > 부분 순이며 원 명칭(alias)으로
 * 잡히면 matched_alias 에 그 명칭이 온다. Turnstile 토큰이 필요 없다(app/api/goods/search 주석).
 * 자동완성에 쓸 때는 디바운스(300ms 안팎)와 2글자 이상 조건을 두는 것이 좋다 — 백엔드 한도가
 * 기본 60/minute 이고 1글자 광범위 질의는 결과가 수만 건이다(서버 실측 약 50ms).
 */
export async function searchGoods(
  query: string,
  options: { limit?: number; niceClass?: number; signal?: AbortSignal } = {},
): Promise<GoodsSearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (options.limit !== undefined) params.set("limit", String(options.limit));
  if (options.niceClass !== undefined) {
    params.set("nice_class", String(options.niceClass));
  }

  let response: Response;
  try {
    response = await fetch(`/api/goods/search?${params}`, {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      signal: options.signal,
    });
  } catch (error) {
    networkError(error);
  }

  const body = await assertOk(response);
  const parsed = GoodsSearchResponseSchema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError(
      502,
      "상품 검색 서비스의 응답 형식이 예상과 달라 결과를 표시할 수 없어요.",
      response.headers.get("x-request-id"),
    );
  }
  return parsed.data;
}

/** NICE 45개 류의 명칭·변환표 항목 수 (류 선택 UI용, 정적 데이터). */
export async function fetchGoodsClasses(
  signal?: AbortSignal,
): Promise<GoodsClassesResponse> {
  let response: Response;
  try {
    response = await fetch("/api/goods/classes", {
      method: "GET",
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    networkError(error);
  }

  const body = await assertOk(response);
  const parsed = GoodsClassesResponseSchema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError(
      502,
      "상품 분류 목록의 응답 형식이 예상과 달라 표시할 수 없어요.",
      response.headers.get("x-request-id"),
    );
  }
  return parsed.data;
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
