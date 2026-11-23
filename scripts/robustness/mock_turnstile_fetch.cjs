// 점검용 Node 사전 적재(NODE_OPTIONS=--require …) — 서비스 코드는 고치지 않고, 프로덕션 빌드의
// 중계 서버가 Cloudflare Turnstile 검증(siteverify)을 부를 때 외부로 나가지 않고 이 모의 응답을 받게
// 한다. 백엔드(MARKLENS_BACKEND_URL)·로컬 주소가 아닌 다른 외부 fetch 는 모두 막는다(외부 호출 0).
//
// 토큰 규칙: "deny…" → success false, "wronghost…" → 다른 호스트 이름, "wrongaction…" → 다른 action,
// 그 밖 → success true(hostname localhost, action marklens). 받은 remoteip 는 ROBUSTNESS_TURNSTILE_LOG
// 파일에 한 줄씩 남긴다(중계 서버가 사용자 IP 를 어디서 읽는지 확인용).
"use strict";

const fs = require("node:fs");

const VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const LOG = process.env.ROBUSTNESS_TURNSTILE_LOG || "";
const original = globalThis.fetch;

function local(url) {
  try {
    const host = new URL(url).hostname;
    return host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]";
  } catch {
    return false;
  }
}

globalThis.fetch = async function mockedFetch(input, init) {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (url.startsWith(VERIFY)) {
    let body = {};
    try {
      body = JSON.parse(init && typeof init.body === "string" ? init.body : "{}");
    } catch {
      body = {};
    }
    const token = String(body.response || "");
    if (LOG) {
      fs.appendFileSync(LOG, JSON.stringify({ at: new Date().toISOString(), remoteip: body.remoteip ?? null,
        token: token.slice(0, 24) }) + "\n");
    }
    const result = token.startsWith("deny")
      ? { success: false, "error-codes": ["invalid-input-response"] }
      : token.startsWith("wronghost")
        ? { success: true, hostname: "evil.example", action: "marklens" }
        : token.startsWith("wrongaction")
          ? { success: true, hostname: "localhost", action: "other" }
          : { success: true, hostname: "localhost", action: "marklens" };
    return new Response(JSON.stringify(result), { status: 200, headers: { "content-type": "application/json" } });
  }
  if (!local(url)) {
    throw new TypeError(`robustness mock: blocked external fetch to ${new URL(url).hostname}`);
  }
  return original(input, init);
};
