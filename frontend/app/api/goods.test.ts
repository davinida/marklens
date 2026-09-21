// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET as getClasses } from "@/app/api/goods/classes/route";
import { GET as searchGoods } from "@/app/api/goods/search/route";

describe("same-origin /api/goods/*", () => {
  beforeEach(() => {
    vi.stubEnv("MARKLENS_BACKEND_URL", "https://backend.example");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", "private-key");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => vi.unstubAllEnvs());

  it("forwards the validated query with the API key and without a Turnstile token", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ query: "화장품", matches: [], total: 0, source: "고시상품명칭 13판(2026)" }),
    );

    const response = await searchGoods(
      new Request(
        "http://localhost/api/goods/search?q=%20화장품%20&limit=5&nice_class=3",
        { headers: { "x-request-id": "edge-goods-1" } },
      ),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-request-id")).toBe("edge-goods-1");
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    // 앞뒤 공백은 잘라서 보내고, limit·nice_class 는 준 것만 전달
    expect(url).toBe(
      "https://backend.example/goods/search?q=%ED%99%94%EC%9E%A5%ED%92%88&limit=5&nice_class=3",
    );
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
    expect(options).toEqual(expect.objectContaining({ method: "GET", cache: "no-store" }));
  });

  it("rejects a blank, over-long or out-of-range query before contacting the backend", async () => {
    for (const query of [
      "?q=",
      "?q=%20%20",
      `?q=${"가".repeat(51)}`,
      "?q=커피&limit=0",
      "?q=커피&limit=51",
      "?q=커피&nice_class=46",
      "",
    ]) {
      const response = await searchGoods(
        new Request(`http://localhost/api/goods/search${query}`),
      );
      expect(response.status).toBe(422);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("proxies the class list with the API key and caches successful responses", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ classes: [], total_entries: 0, source: "고시상품명칭 13판(2026)" }),
    );

    const response = await getClasses(
      new Request("http://localhost/api/goods/classes", {
        headers: { "x-request-id": "edge-goods-2" },
      }),
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("public, max-age=3600");
    expect(response.headers.get("x-request-id")).toBe("edge-goods-2");
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://backend.example/goods/classes");
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
  });
});
