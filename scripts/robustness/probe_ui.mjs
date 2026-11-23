// 화면 점검 — 프로덕션 빌드(3000·3001·3002)에서 입력 경계·오류 문구·스크립트 실행 여부를 보고 캡처한다.
// 외부 요청은 모두 막고 Cloudflare Turnstile 스크립트는 즉시 토큰을 주는 가짜 위젯으로 바꾼다(외부 호출 0).
//
//   bash scripts/robustness/servers.sh start --default-limits && bash scripts/robustness/servers.sh start-extra
//   node scripts/robustness/probe_ui.mjs [출력 폴더] [--only U7,U18]   # --only 는 그 id 결과만 바꿔 씀
// 캡처·결과는 출력 폴더(기본 ~/marklens-archive/robustness-YYYYMMDD)/ui/ 아래 — 저장소에 넣지 않는다.
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("@playwright/test");

const args = process.argv.slice(2);
const onlyIndex = args.indexOf("--only");
const only = onlyIndex >= 0 ? args[onlyIndex + 1] : "";
const onlyIds = only ? only.split(",") : [];
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const today = new Date().toISOString().slice(0, 10).replaceAll("-", "");
const OUT = args.find((a) => !a.startsWith("--") && a !== only) ||
  path.join(os.homedir(), "marklens-archive", `robustness-${today}`);
const IMAGES = path.join(OUT, "images");
const UI = path.join(OUT, "ui");
fs.mkdirSync(UI, { recursive: true });

const STUB = `window.turnstile = { _o: {}, render(el, o) { const id = String(Math.random());
  this._o[id] = o; setTimeout(() => o.callback("ok-" + Date.now()), 30); return id; },
  reset(id) { const o = this._o[id]; if (o) setTimeout(() => o.callback("ok-" + Date.now()), 30); },
  remove(id) { delete this._o[id]; }, getResponse() { return null; } };`;

async function newPage(browser, base, viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport, locale: "ko-KR" });
  await context.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "challenges.cloudflare.com") {
      return route.fulfill({ status: 200, contentType: "application/javascript", body: STUB });
    }
    if (!["127.0.0.1", "localhost"].includes(url.hostname)) return route.abort();
    return route.continue();
  });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => { if (msg.type() === "error") consoleErrors.push(msg.text().slice(0, 200)); });
  page.on("dialog", async (dialog) => { consoleErrors.push(`dialog:${dialog.message()}`); await dialog.dismiss(); });
  await page.goto(`${base}/`, { waitUntil: "networkidle" });
  await page.waitForTimeout(300);
  return { context, page, consoleErrors };
}

const submit = (page) => page.getByRole("button", { name: "비슷한 상표 찾아보기" });

async function upload(page, file) {
  const source = path.isAbsolute(file) ? file : path.join(IMAGES, file);
  await page.locator('input[type="file"]').setInputFiles(source);
  const dialog = page.getByRole("dialog", { name: "분석할 로고 영역 선택" });
  try {
    await dialog.waitFor({ timeout: 4000 });
    await dialog.getByRole("button", { name: "전체 이미지 사용" }).click({ timeout: 4000 });
    // 자르기(캔버스 → WebP)가 끝나 창이 닫힐 때까지 — 그 전에는 창 뒤 입력칸에 글자가 안 들어간다
    await dialog.waitFor({ state: "detached", timeout: 10000 }).catch(() => {});
    return "자르기 창 → 전체 이미지 사용";
  } catch {
    return "자르기 창 없음";
  }
}

async function search(page, timeout = 60000) {
  const started = Date.now();
  const response = page.waitForResponse((r) => r.url().includes("/api/search/v2"), { timeout });
  await submit(page).click();
  let status = null;
  try {
    status = (await response).status();
  } catch {
    status = "응답 없음";
  }
  await page.waitForTimeout(1200);
  return { status, ms: Date.now() - started };
}

async function visibleText(page) {
  const alerts = await page.locator('[role="alert"]').allInnerTexts().catch(() => []);
  const main = (await page.locator("main").innerText().catch(() => "")).replace(/\s+/g, " ").slice(0, 500);
  return { alerts: alerts.map((t) => t.replace(/\s+/g, " ").slice(0, 300)), main };
}

const scenarios = [
  ["U1", "빈 입력 — 검색 버튼", 3000, async (page) => ({ disabled: await submit(page).isDisabled() })],
  ["U2", "이름이 공백뿐", 3000, async (page) => {
    await page.locator("#mark-text").fill("    ");
    return { disabled: await submit(page).isDisabled() };
  }],
  ["U3", "이름이 폭 없는 문자뿐(U+200B)", 3000, async (page) => {
    await page.locator("#mark-text").fill("\u200b\u200b");
    const disabled = await submit(page).isDisabled();
    return disabled ? { disabled } : { disabled, ...(await search(page)) };
  }],
  ["U4", "이름 150자 입력", 3000, async (page) => {
    await page.locator("#mark-text").fill("블".repeat(150));
    const value = await page.locator("#mark-text").inputValue();
    return { length: [...value].length };
  }],
  ["U5", "스크립트 조각 이름", 3000, async (page) => {
    await page.locator("#mark-text").fill('<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>');
    const result = await search(page);
    return { ...result, xss: await page.evaluate(() => window.__xss ?? null) };
  }],
  ["U6", "이모지·NFD 이름", 3000, async (page) => {
    await page.locator("#mark-text").fill("☕" + "블루커피".normalize("NFD"));
    return await search(page);
  }],
  ["U7", "하얀 빈 이미지", 3000, async (page) => ({ upload: await upload(page, "white.png"), ...(await search(page)) })],
  ["U8", "완전 투명 PNG", 3000, async (page) => ({ upload: await upload(page, "fully_transparent.png"), ...(await search(page)) })],
  ["U9", "17MB 이미지", 3000, async (page) => ({ upload: await upload(page, "big_12mb.png"), disabled: await submit(page).isDisabled() })],
  ["U10", "SVG(accept 우회)", 3000, async (page) => ({ upload: await upload(page, "logo.svg"), disabled: await submit(page).isDisabled() })],
  ["U11", "깨진 PNG", 3000, async (page) => ({ upload: await upload(page, "broken_truncated.png"), disabled: await submit(page).isDisabled() })],
  ["U12", "1×1 이미지", 3000, async (page) => {
    const how = await upload(page, "1x1.png");
    const disabled = await submit(page).isDisabled();
    return disabled ? { upload: how, disabled } : { upload: how, ...(await search(page)) };
  }],
  ["U13", "가늘고 긴 4000×32", 3000, async (page) => ({ upload: await upload(page, "thin_4000x32.png"), ...(await search(page)) })],
  ["U14", "APNG(애니메이션)", 3000, async (page) => ({ upload: await upload(page, "animated.png"), ...(await search(page)) })],
  ["U15", "백엔드 꺼짐(3002 → 빈 포트)", 3002, async (page) => {
    await page.locator("#mark-text").fill("블루커피");
    return await search(page);
  }],
  ["U16", "백엔드 멈춤(SIGSTOP 35초)", 3000, async (page) => {
    const pid = Number(fs.readFileSync(path.join(OUT, "backend.pid"), "utf8").trim());
    await page.locator("#mark-text").fill("멈춤 확인 커피");
    process.kill(pid, "SIGSTOP");
    try {
      return await search(page, 70000);
    } finally {
      process.kill(pid, "SIGCONT");
    }
  }],
  ["U17", "검색 한도 초과(3001 → 기본 한도 백엔드)", 3001, async (page) => {
    const key = fs.readFileSync(path.join(OUT, "api_key"), "utf8").trim();
    for (let i = 0; i < 12; i += 1) {  // 같은 IP(127.0.0.1) 묶음을 먼저 채운다
      execFileSync("curl", ["-s", "-o", "/dev/null", "-X", "POST", "-H", `X-API-Key: ${key}`,
        "-F", "goods_codes=G0301", "http://127.0.0.1:8001/search/v2"]);
    }
    await page.locator("#mark-text").fill("블루커피");
    return await search(page);
  }],
  // 결과가 이상한 입력(점검 2)의 P0 두 건 — 결과 화면이 무엇을 보여 주는지(DB 로고라 캡처는 보관 폴더에만)
  ["U18", "R-P0-1 등록 로고 그대로 + 다른 이름(몬테로사)", 3000, async (page) => {
    const logo = path.join(ROOT, "ml", "data", "images", "4020200011726.png");
    await page.locator("#mark-text").fill("몬테로사");  // E2E 와 같은 순서(이름 → 로고)
    const how = await upload(page, logo);
    return { upload: how, name: await page.locator("#mark-text").inputValue(), ...(await search(page)) };
  }],
  ["U19", "R-P0-2 설명적 낱말만(맛있는 커피 전문점) + 카페", 3000, async (page) => {
    await page.locator("#mark-text").fill("맛있는 커피 전문점");
    await page.getByRole("combobox", { name: "지정상품 검색" }).fill("카페");  // E2E 의 업종 세트 흐름
    await page.getByRole("region", { name: "카페 업종 세트" })
      .getByRole("button", { name: "3개 모두 추가" }).click({ timeout: 10000 });
    await page.getByText("선택 3개").waitFor({ timeout: 5000 });
    return await search(page);
  }],
  // 로고를 먼저 올리고 이름을 나중에 넣어도 요청에 이름이 실리는지(U18 첫 시도에서 이름이 빠졌다 —
  // 자르기 창이 닫히기 전에 입력한 시험 순서 탓이었고, 창이 닫힌 뒤 입력하면 실린다)
  ["U20", "로고 먼저 → 이름 나중 — 요청 본문에 이름이 있는지", 3000, async (page) => {
    const how = await upload(page, "ok.png");
    await page.locator("#mark-text").fill("블루커피");
    const typed = await page.locator("#mark-text").inputValue();
    const request = page.waitForRequest((r) => r.url().includes("/api/search/v2"), { timeout: 30000 });
    const result = await search(page);
    const body = (await request).postDataBuffer()?.toString("utf8") ?? "";
    return { upload: how, typed, nameSent: /name="name"\r\n\r\n블루커피/.test(body),
      fields: [...body.matchAll(/name="([^"]+)"/g)].map((m) => m[1]), ...result };
  }],
  ["U21", "이름 먼저 → 로고 나중 — 요청 본문에 이름이 있는지(대조)", 3000, async (page) => {
    await page.locator("#mark-text").fill("블루커피");
    const how = await upload(page, "ok.png");
    const request = page.waitForRequest((r) => r.url().includes("/api/search/v2"), { timeout: 30000 });
    const result = await search(page);
    const body = (await request).postDataBuffer()?.toString("utf8") ?? "";
    return { upload: how, nameSent: /name="name"\r\n\r\n블루커피/.test(body),
      fields: [...body.matchAll(/name="([^"]+)"/g)].map((m) => m[1]), ...result };
  }],
];

const browser = await chromium.launch();
const results = [];
for (const [id, title, port, run] of scenarios) {
  if (onlyIds.length && !onlyIds.includes(id)) continue;
  const { context, page, consoleErrors } = await newPage(browser, `http://localhost:${port}`);
  let outcome;
  try {
    outcome = await run(page);
  } catch (error) {
    outcome = { error: String(error).slice(0, 300) };
  }
  const text = await visibleText(page);
  await page.screenshot({ path: path.join(UI, `${id}.png`), fullPage: true });
  results.push({ id, title, port, ...outcome, ...text, consoleErrors });
  console.log(`${id} ${title}: ${JSON.stringify(outcome)} | ${text.alerts.join(" / ").slice(0, 160)}`);
  await context.close();
}
await browser.close();
// --only 로 일부만 돌리면 앞선 결과에서 같은 id 만 바꿔 쓴다
const file = path.join(UI, "probe_ui.json");
const kept = onlyIds.length && fs.existsSync(file)
  ? JSON.parse(fs.readFileSync(file, "utf8")).filter((r) => !onlyIds.includes(r.id))
  : [];
const merged = [...kept, ...results].sort((a, b) => Number(a.id.slice(1)) - Number(b.id.slice(1)));
fs.writeFileSync(file, JSON.stringify(merged, null, 1) + "\n");
console.log(`\n${results.length}건 → ${UI}`);
