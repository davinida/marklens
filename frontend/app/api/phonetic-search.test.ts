// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as phoneticSearch } from "@/app/api/phonetic-search/route";

describe("same-origin /api/phonetic-search", () => {
  beforeEach(() => {
    vi.stubEnv("MARKLENS_BACKEND_URL", "https://backend.example");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", "private-key");
    vi.stubEnv("MARKLENS_TURNSTILE_DEV_BYPASS", "1");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => vi.unstubAllEnvs());

  it("verifies the token, attaches the API key and forwards only the body contract", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ query: { name: "스타박스" }, matches: [] }),
    );

    const response = await phoneticSearch(
      new Request("http://localhost/api/phonetic-search", {
        method: "POST",
        headers: { "content-type": "application/json", "x-request-id": "edge-phonetic-1" },
        body: JSON.stringify({ name: "스타박스", turnstileToken: "dev-bypass", top_k: 3 }),
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-request-id")).toBe("edge-phonetic-1");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://backend.example/phonetic-search");
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
    expect(JSON.parse(String(options?.body))).toEqual({ name: "스타박스", top_k: 3 });
  });

  it("rejects a request without a verification token before contacting the backend", async () => {
    const response = await phoneticSearch(
      new Request("http://localhost/api/phonetic-search", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "스타박스" }),
      }),
    );

    expect(response.status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });
});
