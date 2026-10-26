// @vitest-environment node

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST as searchV2 } from "@/app/api/search/v2/route";

function image(type = "image/png", size = 5): File {
  return new File([new Uint8Array(size)], "logo.png", { type });
}

function request(form: FormData, query = "", headers?: HeadersInit): Request {
  return new Request(`http://localhost/api/search/v2${query}`, {
    method: "POST",
    headers: { "x-turnstile-token": "dev-bypass", "x-request-id": "v2-request-1", ...headers },
    body: form,
  });
}

function nameForm(name = "MarkLens"): FormData {
  const form = new FormData();
  form.append("name", name);
  return form;
}

describe("POST /api/search/v2", () => {
  beforeEach(() => {
    vi.stubEnv("NODE_ENV", "test");
    vi.stubEnv("MARKLENS_BACKEND_URL", "https://backend.example");
    vi.stubEnv("MARKLENS_BACKEND_API_KEY", "private-key");
    vi.stubEnv("MARKLENS_TURNSTILE_DEV_BYPASS", "1");
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => Response.json({ ok: true })));
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it.each([1, 2, 3, 4, 5, 6, 7])("accepts nonempty input combination %i", async (mask) => {
    const form = new FormData();
    if (mask & 1) form.append("image", image());
    if (mask & 2) form.append("name", "MarkLens");
    if (mask & 4) form.append("goods_codes", "G0502");
    const response = await searchV2(request(form));
    expect(response.status).toBe(200);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("https://backend.example/search/v2?top_k=5");
    const sent = vi.mocked(fetch).mock.calls[0][1]?.body as FormData;
    expect(sent.has("image")).toBe(Boolean(mask & 1));
    expect(sent.has("name")).toBe(Boolean(mask & 2));
    expect(sent.has("goods_codes")).toBe(Boolean(mask & 4));
  });

  it("normalizes names and repeated/comma-separated goods, forwarding only validated fields", async () => {
    const form = nameForm("  블루커피  ");
    form.append("goods_codes", " g0502, S120602 , ,g0502");
    form.append("goods_codes", "s2005,G0301");
    form.append("type_override", "결합");
    form.append("turnstile_token", "secret-token");
    form.append("untrusted", "discard me");
    form.append("file", image());
    const response = await searchV2(request(form, "?top_k=20"));
    expect(response.status).toBe(200);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://backend.example/search/v2?top_k=20");
    const sent = options?.body as FormData;
    expect([...sent.entries()]).toEqual([
      ["name", "블루커피"], ["goods_codes", "G0502"], ["goods_codes", "S120602"],
      ["goods_codes", "S2005"], ["goods_codes", "G0301"], ["type_override", "결합"],
    ]);
    expect(new Headers(options?.headers).get("x-turnstile-token")).toBeNull();
    expect(new Headers(options?.headers).get("x-api-key")).toBe("private-key");
    expect(new Headers(options?.headers).get("x-request-id")).toBe("v2-request-1");
    expect(options).toMatchObject({ method: "POST", cache: "no-store", redirect: "error", signal: expect.any(AbortSignal) });
  });

  it.each(["", "   "])("rejects an empty normalized query (%j)", async (name) => {
    const form = nameForm(name);
    form.append("goods_codes", " , , ");
    form.append("type_override", "문자");
    const response = await searchV2(request(form));
    expect(response.status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not treat legacy file as image", async () => {
    const form = new FormData();
    form.append("file", image());
    expect((await searchV2(request(form))).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("checks content length before top_k, token verification and multipart parsing", async () => {
    const req = new Request("http://localhost/api/search/v2?top_k=bad", {
      method: "POST", headers: { "content-length": String(11 * 1024 * 1024 + 1) }, body: "broken",
    });
    const parse = vi.spyOn(req, "formData");
    expect((await searchV2(req)).status).toBe(413);
    expect(parse).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["0", "21", "1.2", "bad", "Infinity", "-1", "", "1.0", "0x10", "1e1", "%20", "5&top_k=5"])("rejects invalid top_k=%s before token and parsing", async (value) => {
    const req = new Request(`http://localhost/api/search/v2?top_k=${value}`, { method: "POST", body: "broken" });
    const parse = vi.spyOn(req, "formData");
    expect((await searchV2(req)).status).toBe(422);
    expect(parse).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["1", "20"])("accepts top_k boundary %s", async (value) => {
    expect((await searchV2(request(nameForm(), `?top_k=${value}`))).status).toBe(200);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(`https://backend.example/search/v2?top_k=${value}`);
  });

  it("rejects a missing token before parsing the multipart body", async () => {
    const req = new Request("http://localhost/api/search/v2", { method: "POST", body: "broken" });
    const parse = vi.spyOn(req, "formData");
    const response = await searchV2(req);
    expect(response.status).toBe(403);
    expect(parse).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("stops after failed verification without parsing or calling the backend", async () => {
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "test-secret");
    vi.mocked(fetch).mockResolvedValue(Response.json({ success: false }));
    const req = request(nameForm(), "", { "x-turnstile-token": "real-token" });
    const parse = vi.spyOn(req, "formData");
    expect((await searchV2(req)).status).toBe(403);
    expect(parse).not.toHaveBeenCalled();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("https://challenges.cloudflare.com/turnstile/v0/siteverify");
  });

  it("verifies the token before parsing a successful request", async () => {
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "test-secret");
    const events: string[] = [];
    vi.mocked(fetch).mockImplementation(async (url) => {
      events.push(String(url).includes("siteverify") ? "verify" : "backend");
      return Response.json({ success: true, action: "marklens" });
    });
    const req = request(nameForm(), "", { "x-turnstile-token": "real-token" });
    const parse = req.formData.bind(req);
    vi.spyOn(req, "formData").mockImplementation(async () => { events.push("parse"); return parse(); });
    expect((await searchV2(req)).status).toBe(200);
    expect(events).toEqual(["verify", "parse", "backend"]);
  });

  it("maps unavailable verification configuration to 503", async () => {
    vi.stubEnv("MARKLENS_TURNSTILE_SECRET_KEY", "");
    expect((await searchV2(request(nameForm(), "", { "x-turnstile-token": "real-token" }))).status).toBe(503);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects malformed multipart after verification", async () => {
    const req = new Request("http://localhost/api/search/v2", {
      method: "POST", headers: { "x-turnstile-token": "dev-bypass", "content-type": "multipart/form-data; boundary=broken" }, body: "broken",
    });
    expect((await searchV2(req)).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["image/png", "image/jpeg", "image/webp"])("accepts %s images and preserves the file", async (type) => {
    const form = new FormData();
    form.append("image", image(type));
    expect((await searchV2(request(form))).status).toBe(200);
    const sent = (vi.mocked(fetch).mock.calls[0][1]?.body as FormData).get("image") as File;
    expect(sent.type).toBe(type);
    expect(sent.name).toBe("logo.png");
    expect(sent.size).toBe(5);
  });

  it.each([
    ["zero byte", (): File => image("image/png", 0), 400],
    ["oversize", (): File => image("image/png", 10 * 1024 * 1024 + 1), 413],
    ["wrong MIME", (): File => image("image/gif"), 415],
    ["text field", (): string => "logo.png", 415],
  ] as const)("rejects an explicitly invalid image (%s) even with a valid name", async (_label, file, status) => {
    const form = nameForm();
    form.append("image", file());
    expect((await searchV2(request(form))).status).toBe(status);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("accepts an image exactly at 10 MiB", async () => {
    const form = new FormData();
    form.append("image", image("image/png", 10 * 1024 * 1024));
    expect((await searchV2(request(form))).status).toBe(200);
  });

  it("checks image validity before invalid text fields", async () => {
    const form = nameForm("a".repeat(101));
    form.append("image", image("image/gif"));
    expect((await searchV2(request(form))).status).toBe(415);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["image", "name", "type_override"])("rejects repeated scalar %s", async (field) => {
    const form = nameForm();
    if (field === "name") form.append("name", "Second");
    else {
      form.append(field, field === "image" ? image() : "문자");
      form.append(field, field === "image" ? image() : "도형");
    }
    expect((await searchV2(request(form))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["name", "goods_codes", "type_override"])("rejects File-valued text field %s", async (field) => {
    const form = nameForm();
    form.set(field, image());
    expect((await searchV2(request(form))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("counts Unicode code points at the 100-character name boundary", async () => {
    expect((await searchV2(request(nameForm(`  ${"😀".repeat(100)}  `)))).status).toBe(200);
    expect((vi.mocked(fetch).mock.calls[0][1]?.body as FormData).get("name")).toBe("😀".repeat(100));
    vi.mocked(fetch).mockClear();
    expect((await searchV2(request(nameForm("😀".repeat(101))))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["G123", "G1234567", "X1234", "G12a4", "G１２３４"])("rejects malformed goods code %s", async (code) => {
    const form = nameForm();
    form.append("goods_codes", code);
    expect((await searchV2(request(form))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("limits goods to 60 unique normalized codes", async () => {
    const form = nameForm();
    const codes = Array.from({ length: 60 }, (_, index) => `G${String(index).padStart(4, "0")}`);
    form.append("goods_codes", [...codes, ...codes].join(","));
    expect((await searchV2(request(form))).status).toBe(200);
    expect((vi.mocked(fetch).mock.calls[0][1]?.body as FormData).getAll("goods_codes")).toHaveLength(60);
    vi.mocked(fetch).mockClear();
    form.append("goods_codes", "G9999");
    expect((await searchV2(request(form))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each(["문자", "도형", "결합"])("accepts type_override=%s", async (type) => {
    const form = nameForm();
    form.append("type_override", type);
    expect((await searchV2(request(form))).status).toBe(200);
    expect((vi.mocked(fetch).mock.calls[0][1]?.body as FormData).get("type_override")).toBe(type);
  });

  it.each(["", "결합-문자요부", " 문자 "])("rejects invalid type_override=%j", async (type) => {
    const form = nameForm();
    form.append("type_override", type);
    expect((await searchV2(request(form))).status).toBe(422);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([200, 400, 422, 429, 503])("forwards upstream %i body and safe headers without rewriting URLs", async (status) => {
    const body = '{ "image_url": "/images/example.png", "detail": "unchanged" }';
    vi.mocked(fetch).mockResolvedValue(new Response(body, {
      status,
      headers: {
        "content-type": "application/json", "retry-after": "30", "x-ratelimit-limit": "10",
        "x-ratelimit-remaining": "0", "x-ratelimit-reset": "100", "x-api-key": "secret",
        "set-cookie": "private=yes", "x-request-id": "upstream-id", "cache-control": "public",
      },
    }));
    const response = await searchV2(request(nameForm()));
    expect(response.status).toBe(status);
    expect(await response.text()).toBe(body);
    expect(Object.fromEntries(response.headers)).toEqual({
      "content-type": "application/json", "retry-after": "30", "x-ratelimit-limit": "10",
      "x-ratelimit-remaining": "0", "x-ratelimit-reset": "100", "x-request-id": "v2-request-1", "cache-control": "no-store",
    });
  });

  it.each([
    [new TypeError("connection failed"), 502],
    [new DOMException("timed out", "TimeoutError"), 504],
    [new DOMException("cancelled", "AbortError"), 499],
  ] as const)("maps upstream failure to %i", async (error, status) => {
    vi.mocked(fetch).mockRejectedValue(error);
    const response = await searchV2(request(nameForm()));
    expect(response.status).toBe(status);
    expect(response.headers.get("x-request-id")).toBe("v2-request-1");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("passes request cancellation into the upstream abort signal", async () => {
    const controller = new AbortController();
    const base = request(nameForm());
    const req = new Request(base, { signal: controller.signal });
    controller.abort();
    await searchV2(req);
    const signal = vi.mocked(fetch).mock.calls[0][1]?.signal;
    expect(signal?.aborted).toBe(true);
  });
});
