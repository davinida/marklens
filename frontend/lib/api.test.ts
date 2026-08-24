// @vitest-environment node

import { beforeEach, describe, expect, it, vi } from "vitest";
import { imageUrl, searchTrademark } from "@/lib/api";

const validResponse = {
  grade: {
    grade_code: "SAFE",
    grade_name: "낮음",
    message: "충돌 가능성이 낮아요.",
    top1_similarity: 0.2,
    separability_a: 0.1,
    separability_b: 0.1,
    warnings: [],
  },
  matches: [],
  dataset_info: {
    총_상표수: 1,
    출원일자_범위: "2026",
    데이터_기준: "테스트",
    생성일자: "2026-08-14",
  },
  index_size: 1,
  top_k_requested: 5,
  top_k_returned: 0,
};

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

describe("searchTrademark", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));

  it("sends the upload only to the same-origin route", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify(validResponse), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const file = new File(["image"], "logo.png", { type: "image/png" });

    await expect(searchTrademark(file, 5, "token")).resolves.toMatchObject({
      index_size: 1,
    });

    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/search?top_k=5");
    expect(options?.credentials).toBe("same-origin");
    expect(new Headers(options?.headers).get("x-turnstile-token")).toBe("token");
    expect(options?.body).toBeInstanceOf(FormData);
  });

  it("fails closed when the backend contract is malformed", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ matches: [] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await expect(
      searchTrademark(
        new File(["image"], "logo.png", { type: "image/png" }),
        5,
        "token",
      ),
    ).rejects.toEqual(
      expect.objectContaining({ status: 502, name: "ApiError" }),
    );
  });
});
