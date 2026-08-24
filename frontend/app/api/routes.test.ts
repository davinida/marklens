// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET as getHealth } from "@/app/api/health/route";
import { GET as getImage } from "@/app/api/images/[...path]/route";
import { POST as checkName } from "@/app/api/name-check/route";
import { POST as search } from "@/app/api/search/route";
import { verifyTurnstile } from "@/lib/server/turnstile";

describe("same-origin API routes", () => {
  beforeEach(() => {
    vi.stubEnv("MARKLENS_BACKEND_URL", "https://backend.example");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", "private-key");
    vi.stubEnv("MARKLENS_TURNSTILE_DEV_BYPASS", "1");
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => vi.unstubAllEnvs());

  it("keeps the API key and verification token out of the browser-facing search", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: {
          "content-type": "application/json",
          "x-request-id": "upstream-id",
        },
      }),
    );
    const form = new FormData();
    form.set("file", new File(["image"], "logo.png", { type: "image/png" }));

    const response = await search(
      new Request("http://localhost/api/search?top_k=5", {
        method: "POST",
        headers: {
          "x-request-id": "edge-search-1",
          "x-turnstile-token": "dev-bypass",
        },
        body: form,
      }),
    );

    expect(response.status).toBe(200);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://backend.example/search?top_k=5");
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
    expect(new Headers(options?.headers).get("x-request-id")).toBe(
      "edge-search-1",
    );
    expect(response.headers.get("x-request-id")).toBe("edge-search-1");
    const upstreamForm = options?.body as FormData;
    expect(upstreamForm.get("file")).toBeInstanceOf(File);
    expect(upstreamForm.has("turnstile_token")).toBe(false);
  });

  it("rejects an unverified upload before parsing multipart data", async () => {
    const response = await search(
      new Request("http://localhost/api/search?top_k=5", {
        method: "POST",
        headers: {
          "content-type": "multipart/form-data; boundary=broken",
          "x-request-id": "edge-rejected-1",
        },
        body: "not multipart data",
      }),
    );

    expect(response.status).toBe(403);
    expect(response.headers.get("x-request-id")).toBe("edge-rejected-1");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("falls back to the legacy GET name contract only for 404/405", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(null, { status: 405 }))
      .mockResolvedValueOnce(
        Response.json({
          query: "MarkLens",
          total_found: 0,
          registered_count: 0,
          exact_registered_count: 0,
          cached: true,
          message: "없음",
        }),
      );

    const response = await checkName(
      new Request("http://localhost/api/name-check", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "MarkLens", turnstileToken: "dev-bypass" }),
      }),
    );

    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenNthCalledWith(
      1,
      "https://backend.example/name-check",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      "https://backend.example/name-check?name=MarkLens",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("rejects unsafe image path segments before contacting the backend", async () => {
    const response = await getImage(
      new Request("http://localhost/api/images/../secret.png", {
        headers: { "x-request-id": "edge-image-1" },
      }),
      { params: Promise.resolve({ path: ["..", "secret.png"] }) },
    );

    expect(response.status).toBe(400);
    expect(response.headers.get("x-request-id")).toBe("edge-image-1");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("proxies a sanitized backend health response with server credentials", async () => {
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        status: "ok",
        engine_ready: true,
        index_size: 120,
        trademark_count: 100,
        storage_mode: "db",
        artifact_generation_id: "internal-generation-id",
      }),
    );

    const response = await getHealth(
      new Request("http://localhost/api/health", {
        headers: { "x-request-id": "edge-health-1" },
      }),
    );

    expect(response.status).toBe(200);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://backend.example/health");
    expect(options).toEqual(
      expect.objectContaining({ method: "GET", cache: "no-store" }),
    );
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
    expect(new Headers(options?.headers).get("x-request-id")).toBe(
      "edge-health-1",
    );
    expect(response.headers.get("x-request-id")).toBe("edge-health-1");
    expect(response.headers.has("x-api-key")).toBe(false);
    expect(await response.json()).toEqual({
      status: "ok",
      engine_ready: true,
      index_size: 120,
      trademark_count: 100,
      artifact_generation_id: "internal-generation-id",
    });
  });
});

describe("Turnstile verification", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllEnvs());

  it("does not honor the development bypass in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MARKLENS_TURNSTILE_DEV_BYPASS", "1");
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "");

    await expect(verifyTurnstile("dev-bypass", new Headers())).rejects.toMatchObject({
      status: 503,
    });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("uses the fixed marklens action even if a legacy env override is set", async () => {
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "secret");
    vi.stubEnv("MARKLENS_TURNSTILE_EXPECTED_ACTION", "other");
    vi.stubEnv("MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES", "marklens.example");
    vi.mocked(fetch).mockResolvedValue(
      Response.json({
        success: true,
        action: "marklens",
        hostname: "marklens.example",
      }),
    );

    await expect(
      verifyTurnstile("real-token", new Headers()),
    ).resolves.toBeUndefined();
  });

  it("rejects a valid token response from an unexpected hostname", async () => {
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "secret");
    vi.stubEnv("MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES", "marklens.example");
    vi.mocked(fetch).mockResolvedValue(
      Response.json({ success: true, action: "marklens", hostname: "evil.example" }),
    );

    await expect(verifyTurnstile("real-token", new Headers())).rejects.toMatchObject({
      status: 403,
    });
  });

  it("requires a hostname allowlist in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "secret");
    vi.stubEnv("MARKLENS_TURNSTILE_EXPECTED_HOSTNAMES", "");

    await expect(verifyTurnstile("real-token", new Headers())).rejects.toMatchObject({
      status: 503,
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
