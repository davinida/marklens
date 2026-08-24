import "server-only";

export const REQUEST_ID_HEADER = "X-Request-ID";

const SAFE_REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/;

export function getRequestId(headers: Headers): string {
  const candidate = headers.get(REQUEST_ID_HEADER)?.trim();
  return candidate && SAFE_REQUEST_ID.test(candidate)
    ? candidate
    : crypto.randomUUID();
}

export function headersWithRequestId(
  requestId: string,
  initial?: HeadersInit,
): Headers {
  const headers = new Headers(initial);
  headers.set(REQUEST_ID_HEADER, requestId);
  return headers;
}
