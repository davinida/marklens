// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";
import { imageUrl, searchGoods, searchV2 } from "@/lib/api";
import imageFixture from "@/test/fixtures/search-v2-image.json";

describe("imageUrl", () => {
  it("routes relative and legacy backend image paths through the BFF", () => {
    expect(imageUrl("/images/logo one.png")).toBe("/api/images/logo%20one.png");
    expect(imageUrl("http://127.0.0.1:8000/images/상표.png")).toBe(
      "/api/images/%EC%83%81%ED%91%9C.png",
    );
  });

  it("rejects unsafe schemes, protocol-relative URLs, and traversal", () => {
    expect(imageUrl("javascript:alert(1)")).toBeNull();
    expect(imageUrl("//tracker.example/logo.png")).toBeNull();
    expect(imageUrl("/images/../secret.png")).toBeNull();
    expect(imageUrl("http://example.com/logo.png")).toBeNull();
    expect(imageUrl("/api/images/logo.png")).toBeNull();
    expect(imageUrl("images/logo.png")).toBeNull();
    expect(imageUrl("/images/logo%2Fsecret.png")).toBeNull();
  });

  it("only accepts an absolute URL when it carries a backend image path", () => {
    expect(imageUrl("https://images.example/logo.png")).toBeNull();
    expect(imageUrl("https://backend.example/images/logo.png")).toBe(
      "/api/images/logo.png",
    );
  });
});

describe("searchV2", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("sends the upload only to the same-origin route (ported from v1 searchTrademark)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(imageFixture), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const image = new File(["image"], "logo.png", { type: "image/png" });

    await expect(searchV2({ image }, 5, "token")).resolves.toMatchObject({
      top_k_requested: imageFixture.top_k_requested,
    });

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/search/v2?top_k=5");
    expect(options?.credentials).toBe("same-origin");
    expect(new Headers(options?.headers).get("x-turnstile-token")).toBe("token");
    expect(options?.body).toBeInstanceOf(FormData);
    expect((options?.body as FormData).get("image")).toBeInstanceOf(File);
  });

  it("fails closed when the backend contract is malformed (ported from v1 searchTrademark)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ candidates: [] }), {
        status: 200,
        headers: { "content-type": "application/json", "x-request-id": "bad-contract-1" },
      }),
    );

    await expect(
      searchV2({ image: new File(["image"], "logo.png", { type: "image/png" }) }, 5, "token"),
    ).rejects.toEqual(
      expect.objectContaining({ status: 502, name: "ApiError", requestId: "bad-contract-1" }),
    );
  });
});

describe("searchGoods", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("queries the same-origin route without a Turnstile token and parses the contract", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          query: "화장품 소매업",
          matches: [
            {
              name: "화장품 판매업(도소매·중개·대행)",
              nice_class: 35,
              similarity_codes: ["S2012"],
              matched_alias: "화장품 소매업",
            },
          ],
          total: 1,
          source: "지식재산처 고시상품명칭 13판(2026), 공공누리 제1유형",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await searchGoods("화장품 소매업", { limit: 5, niceClass: 35 });

    expect(result.total).toBe(1);
    expect(result.matches[0].matched_alias).toBe("화장품 소매업");
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe(
      "/api/goods/search?q=%ED%99%94%EC%9E%A5%ED%92%88+%EC%86%8C%EB%A7%A4%EC%97%85&limit=5&nice_class=35",
    );
    expect(options?.credentials).toBe("same-origin");
    expect(new Headers(options?.headers).has("x-turnstile-token")).toBe(false);
  });

  it("omits an empty query and sends offset only when positive (class listing)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({ query: "", matches: [], total: 3, offset: 20, source: "fixture" }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    const result = await searchGoods("  ", { niceClass: 25, offset: 20, limit: 20 });

    expect(result.offset).toBe(20);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
      "/api/goods/search?limit=20&nice_class=25&offset=20",
    );

    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ query: "커피", matches: [], total: 0 }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const defaults = await searchGoods("커피", { offset: 0 });
    expect(defaults.offset).toBe(0); // 응답에 offset 이 없으면 0
    expect(vi.mocked(fetch).mock.calls[1][0]).toBe("/api/goods/search?q=%EC%BB%A4%ED%94%BC");
  });

  it("fails closed when the goods contract is malformed", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ matches: "nope" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(searchGoods("커피")).rejects.toEqual(
      expect.objectContaining({ status: 502, name: "ApiError" }),
    );
  });
});
