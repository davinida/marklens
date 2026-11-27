import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// 접근성 점검(데스크톱) — 입력 화면·결과 화면의 상태를 모의 응답(픽스처)으로 그리고 상태마다
//  ① axe-core 의 critical·serious 위반이 0인지 ② h1 이 하나이고 제목 단계를 건너뛰지 않는지 본다.
// 엔진·백엔드는 띄우지 않는다(모든 /api/* 를 가로챈다). 데스크톱 프로젝트에서만 돈다.
//
// 전·후를 견줄 때: A11Y_OUT=<폴더> 를 주면 상태마다 1440 폭 전체 화면 그림과 axe 결과·제목 구조를
// 그 폴더에 남기고, 위반이 있어도 실패로 치지 않는다(결과물에는 픽스처의 상표 이름이 보이므로 저장소
// 밖 폴더를 준다).
//   A11Y_OUT=~/marklens-archive/a11y-desktop-날짜/before npx playwright test e2e/a11y.spec.ts --project chromium-desktop

const OUT = process.env.A11Y_OUT ? path.resolve(process.env.A11Y_OUT) : null;
const AXE_SOURCE = require.resolve("axe-core/axe.min.js");
const FIXTURES = path.join(__dirname, "..", "test", "fixtures");
const fixture = (name: string) =>
  JSON.parse(fs.readFileSync(path.join(FIXTURES, `search-v2-${name}.json`), "utf-8"));

const LOGO_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAACLSURBVHhe7dAxAQAgEIDAD2Mz438I3akAwy2MzLn7zIbBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYfAJdEkoIltljAAAAAElFTkSuQmCC",
  "base64",
);

const CAFE_PRESET_RESULT = {
  query: "카페",
  matches: [
    { name: "카페서비스업", nice_class: 43, similarity_codes: ["S120602"], matched_alias: null },
  ],
  total: 1,
  offset: 0,
  presets: [
    {
      id: "cafe",
      업종명: "카페",
      emoji: "☕",
      지정상품: [
        { name: "커피전문점업", nice_class: 43, similarity_codes: ["G0301", "G0502", "S120602"] },
        { name: "커피", nice_class: 30, similarity_codes: ["G0502"] },
        { name: "커피 소매업", nice_class: 35, similarity_codes: ["S2005"] },
      ],
    },
  ],
  source: "E2E fixture",
};
const GOODS_CLASSES_RESULT = {
  classes: [
    { nice_class: 30, title: "커피·과자", count: 1 },
    { nice_class: 43, title: "음식점·숙박", count: 1 },
  ],
  total_entries: 2,
  source: "E2E fixture",
};
const DATASET_INFO = {
  총_상표수: 1,
  출원일자_범위: "E2E fixture",
  데이터_기준: "브라우저 테스트",
  생성일자: "2026-08-14",
};
const NAME_CHECK_RESULT = {
  query: "블루커피",
  total_found: 3,
  scanned_count: 3,
  registered_count: 2,
  exact_registered_count: 1,
  exact_title_count: 2,
  status_counts: { 등록: 2, 소멸: 1 },
  candidates: [
    {
      application_number: "4020260012345",
      registration_number: "4012345670000",
      application_date: "20260101",
      registration_date: "20260701",
      title: "블루커피",
      status: "등록",
      mark_type: "일반상표",
      applicant: "예시 출원인",
      right_holder: "예시 출원인",
      nice_classes: ["30", "43"],
      vienna_codes: ["27.05.01"],
      similarity_codes: ["G0502"],
      exact_title_match: true,
      is_registered: true,
      local_image_url: null,
    },
  ],
  candidates_returned: 1,
  candidates_truncated: false,
  complete: true,
  checked_at: "2026-08-14T00:00:00Z",
  source: "KIPRIS browser fixture",
  cached: false,
  // 백엔드 namecheck._to_message 가 만드는 문장(그대로 화면에 보인다)
  message: "동일 명칭의 선행 등록상표 1건이 존재해요.",
};
const PHONETIC_RESULT = {
  query: { name: "블루커피", has_pronunciation: true, candidates: ["블루커피"] },
  matches: [
    {
      rank: 1,
      similarity: 0.67,
      출원번호: "4020260012345",
      상표한글명: "블루핸즈",
      이미지URL: null,
      출원인: "예시 출원인",
      류: [12],
    },
  ],
  searched_count: 1,
  excluded_no_pronunciation: 0,
  dataset_info: DATASET_INFO,
  params: { top_k: 5, min_similarity: 0.5 },
  axis: "X1",
  note: "호칭(발음) 유사도만 반영한 참고 정보",
};
const SEMANTIC_RESULT = {
  query: { name: "블루커피", has_meaning: true, text: "블루커피" },
  matches: [
    {
      rank: 1,
      score: 0.69,
      출원번호: "4020260012345",
      상표한글명: "스타커피",
      이미지URL: null,
      출원인: "예시 출원인",
      류: [43],
    },
  ],
  searched_count: 1,
  excluded_no_meaning: 0,
  dataset_info: DATASET_INFO,
  params: { top_k: 5, min_score: 0.55 },
  threshold: 0.55,
  axis: "X3",
  note: "관념(의미) 유사도만 반영한 참고 정보",
  model: "e2e-fixture",
};

type SearchReply = { status: number; body: unknown; headers?: Record<string, string> };

/** 모든 /api/* 를 모의 응답으로 — 검색 응답은 상태마다 바꿔 끼운다. */
async function mockApi(page: Page, search: () => SearchReply | Promise<SearchReply>) {
  await page.route("**/api/goods/search?*", async (route) => {
    const q = new URL(route.request().url()).searchParams.get("q") ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        q === "카페" ? CAFE_PRESET_RESULT : { query: q, matches: [], total: 0, offset: 0 },
      ),
    });
  });
  await page.route("**/api/goods/classes", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GOODS_CLASSES_RESULT),
    }),
  );
  await page.route("**/api/images/**", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: LOGO_PNG }),
  );
  await page.route("**/api/name-check", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(NAME_CHECK_RESULT),
    }),
  );
  await page.route("**/api/phonetic-search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PHONETIC_RESULT),
    }),
  );
  await page.route("**/api/semantic-search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEMANTIC_RESULT),
    }),
  );
  await page.route("**/api/search/v2*", async (route) => {
    const reply = await search();
    await route.fulfill({
      status: reply.status,
      contentType: "application/json",
      headers: reply.headers,
      body: JSON.stringify(reply.body),
    });
  });
}

const ok = (name: string) => () => ({ status: 200, body: fixture(name) });
/** 비교할 후보가 없는 응답(전체 등급 없음) */
function emptyResult() {
  const body = fixture("text");
  body.overall = {
    ...body.overall,
    grade: null,
    prob: null,
    pattern: null,
    caveats: ["비교할 후보가 없어요 — 안전하다는 뜻이 아니에요"],
  };
  delete body.overall.famous_floor;
  delete body.name_words;
  delete body.cross_goods_more;
  body.candidates = [];
  return body;
}
const RATE_LIMITED: SearchReply = {
  status: 429,
  headers: { "retry-after": "30" },
  body: { detail: "요청이 너무 많아요. 잠시 후 다시 시도하세요. (1분에 10번까지 검색할 수 있어요)" },
};

async function fillName(page: Page, name: string) {
  await page.locator("#mark-text").fill(name);
}
async function chooseLogo(page: Page) {
  await page.locator('input[type="file"]').setInputFiles({
    name: "marklens-e2e.png",
    mimeType: "image/png",
    buffer: LOGO_PNG,
  });
  const dialog = page.getByRole("dialog", { name: "분석할 로고 영역 선택" });
  await dialog.getByRole("button", { name: "전체 이미지 사용" }).click();
  await expect(dialog).toBeHidden();
}
async function chooseCafe(page: Page) {
  await page.getByRole("combobox", { name: "지정상품 검색" }).fill("카페");
  await page
    .getByRole("region", { name: "카페 업종 세트" })
    .getByRole("button", { name: "3개 모두 추가" })
    .click();
  await expect(page.getByText("선택 3개")).toBeVisible();
}
async function search(page: Page) {
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();
}
async function searchToResult(page: Page) {
  await search(page);
  await expect(page.getByTestId("overall-grade")).toBeVisible();
}

type State = {
  id: string;
  title: string;
  reply?: () => SearchReply | Promise<SearchReply>;
  setup: (page: Page) => Promise<void>;
};

// 검색 중 화면은 응답을 붙잡아 두고 그린다(그린 뒤 풀어 준다)
let releaseSearch: () => void = () => {};

const STATES: State[] = [
  { id: "I1_입력_빈_상태", title: "input: empty", setup: async () => {} },
  { id: "I2_입력_이름", title: "input: name typed", setup: (page) => fillName(page, "블루커피") },
  { id: "I3_입력_로고", title: "input: logo chosen", setup: (page) => chooseLogo(page) },
  {
    id: "I3a_입력_로고_영역_고르는_창",
    title: "input: crop dialog",
    setup: async (page) => {
      await page.locator('input[type="file"]').setInputFiles({
        name: "marklens-e2e.png",
        mimeType: "image/png",
        buffer: LOGO_PNG,
      });
      const dialog = page.getByRole("dialog", { name: "분석할 로고 영역 선택" });
      await expect(dialog.getByRole("button", { name: "전체 이미지 사용" })).toBeEnabled();
    },
  },
  { id: "I4_입력_업종", title: "input: goods chosen", setup: (page) => chooseCafe(page) },
  {
    id: "I5_입력_오류",
    title: "input: errors",
    setup: async (page) => {
      // 올릴 수 없는 파일 + 이름 확인 실패(특허청 조회 서비스 응답 없음 — 모의 502)
      await page.unroute("**/api/name-check");
      await page.route("**/api/name-check", (route) =>
        route.fulfill({
          status: 502,
          contentType: "application/json",
          body: JSON.stringify({ detail: "KIPRIS 상표명 확인 서비스 응답을 확인하지 못했어요." }),
        }),
      );
      await page.locator('input[type="file"]').setInputFiles({
        name: "notes.txt",
        mimeType: "text/plain",
        buffer: Buffer.from("not an image"),
      });
      await expect(page.getByText("PNG, JPG, WEBP 파일만 올릴 수 있어요.")).toBeVisible();
      await fillName(page, "블루커피");
      await page.getByRole("button", { name: "이름 확인" }).click();
      await expect(page.getByText(/특허청 조회 서비스에서 응답을 받지 못했어요/)).toBeVisible();
    },
  },
  {
    id: "I6_입력_이름_확인_결과",
    title: "input: name check result",
    setup: async (page) => {
      await fillName(page, "블루커피");
      await page.getByRole("button", { name: "이름 확인" }).click();
      await expect(page.getByRole("heading", { name: "관념 유사 후보" })).toBeVisible();
      await expect(page.getByText("69%")).toBeVisible();
    },
  },
  {
    id: "L1_검색_중",
    title: "loading",
    reply: () =>
      new Promise<SearchReply>((resolve) => {
        releaseSearch = () => resolve({ status: 200, body: fixture("text") });
      }),
    setup: async (page) => {
      await fillName(page, "블루커피");
      await search(page);
      await expect(page.getByRole("button", { name: "취소하고 입력으로 돌아가기" })).toBeVisible();
    },
  },
  {
    id: "R1_결과_이름+업종",
    title: "result: name + goods",
    reply: ok("text"),
    setup: async (page) => {
      await fillName(page, "블루커피");
      await chooseCafe(page);
      await searchToResult(page);
    },
  },
  {
    id: "R1a_결과_후보_카드_펼침",
    title: "result: candidate card expanded",
    reply: ok("text"),
    setup: async (page) => {
      await fillName(page, "블루커피");
      await chooseCafe(page);
      await searchToResult(page);
      await page
        .getByRole("region", { name: "유사 상표 후보" })
        .locator(":scope > ul > li")
        .first()
        .getByRole("button")
        .first()
        .click();
      await expect(page.getByText("등급 근거 축", { exact: true })).toBeVisible();
    },
  },
  {
    id: "R2_결과_로고만",
    title: "result: logo only",
    reply: ok("image"),
    setup: async (page) => {
      await chooseLogo(page);
      await searchToResult(page);
    },
  },
  {
    id: "R2a_결과_로고만_사진_안내",
    title: "result: logo only, judged a photo",
    reply: () => {
      const body = fixture("image");
      body.overall.caveats = [
        ...body.overall.caveats,
        "사진으로 보여요 — 로고 파일을 올리면 외관 비교가 더 정확해요",
      ];
      return { status: 200, body };
    },
    setup: async (page) => {
      await chooseLogo(page);
      await searchToResult(page);
      await expect(page.getByTestId("photo-notice")).toBeVisible();
    },
  },
  {
    id: "R3_결과_유명_상표_배너",
    title: "result: famous banner",
    reply: ok("famous"),
    setup: async (page) => {
      await fillName(page, "스타벅스");
      await chooseCafe(page);
      await searchToResult(page);
      await expect(page.getByTestId("famous-banner")).toBeVisible();
    },
  },
  {
    id: "R4_결과_설명적_이름_안내",
    title: "result: descriptive-name notice",
    reply: ok("descriptive"),
    setup: async (page) => {
      await fillName(page, "맛있는 커피 전문점");
      await chooseCafe(page);
      await searchToResult(page);
      await expect(page.getByTestId("descriptive-notice")).toBeVisible();
    },
  },
  {
    id: "R5_결과_업종_다름",
    title: "result: different-business marks",
    reply: ok("famous"),
    setup: async (page) => {
      await fillName(page, "스타벅스");
      await chooseCafe(page);
      await searchToResult(page);
      await page.getByTestId("cross-goods-more-toggle").click();
      await expect(page.getByTestId("cross-goods-more-panel")).toBeVisible();
    },
  },
  {
    id: "R6_결과_오류_화면",
    title: "result: error screen",
    reply: () => RATE_LIMITED,
    setup: async (page) => {
      await fillName(page, "블루커피");
      await search(page);
      await expect(page.getByRole("heading", { name: "검색을 완료하지 못했어요" })).toBeVisible();
    },
  },
  {
    id: "R7_결과_후보_없음",
    title: "result: no candidates",
    reply: () => ({ status: 200, body: emptyResult() }),
    setup: async (page) => {
      await fillName(page, "블루커피");
      await search(page);
      await expect(page.getByRole("button", { name: "다른 로고 비교하기" })).toBeVisible();
    },
  },
];

// 색을 바꿔야 고칠 수 있어 그대로 둔 위반(눈에 보이는 모습은 바꾸지 않는다는 조건 — docs/MarkLens_UI_평가.md §6).
// 0절의 상태(입력 다섯·결과 여섯)에는 해당이 없고, 더 본 두 상태에만 있다. 고치면 여기서 지운다.
const KNOWN: Record<string, string[]> = {
  // 이름 확인 패널의 "확인 필요" 표시 — 글자색 review-deep 이 review-bg 위에서 4.5:1 에 못 미친다
  I6_입력_이름_확인_결과: ["color-contrast"],
  // 펼친 후보 카드의 규칙 사유 줄 — 같은 글자색
  R1a_결과_후보_카드_펼침: ["color-contrast"],
};

type Violation = { id: string; impact: string | null; help: string; nodes: string[]; detail: string[] };

async function runAxe(page: Page): Promise<Violation[]> {
  await page.addScriptTag({ path: AXE_SOURCE });
  return page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- axe 는 주입한 전역
    const axe = (window as any).axe;
    // Next 개발 서버의 표시(nextjs-portal)는 우리 화면이 아니다
    const found = await axe.run(
      { exclude: [["nextjs-portal"]] },
      { resultTypes: ["violations"] },
    );
    return found.violations.map(
      (item: {
        id: string;
        impact: string | null;
        help: string;
        nodes: { target: unknown[]; any: { message: string }[] }[];
      }) => ({
        id: item.id,
        impact: item.impact,
        help: item.help,
        nodes: item.nodes.map((node) => node.target.join(" ")),
        detail: item.nodes.map((node) => node.any.map((check) => check.message).join(" / ")),
      }),
    );
  });
}

type Heading = { level: number; text: string };

/** 화면 낭독기가 읽는 제목(숨긴 영역 제외, 화면에만 안 보이는 sr-only 는 포함)을 문서 순서로. */
async function headings(page: Page): Promise<Heading[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")]
      .filter((node) => {
        if (node.closest("nextjs-portal, [hidden], [aria-hidden='true']")) return false;
        return (node as HTMLElement).getClientRects().length > 0;
      })
      .map((node) => ({
        level: Number(node.tagName.slice(1)),
        text: (node.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 60),
      })),
  );
}

function headingProblems(list: Heading[]): string[] {
  const problems: string[] = [];
  const h1 = list.filter((item) => item.level === 1).length;
  if (h1 !== 1) problems.push(`h1 이 ${h1}개`);
  let previous = 0;
  for (const item of list) {
    if (item.level > previous + 1) {
      problems.push(`h${previous} 다음에 h${item.level} "${item.text}"`);
    }
    previous = item.level;
  }
  return problems;
}

test.use(OUT ? { viewport: { width: 1440, height: 900 } } : {});

test.describe("accessibility — desktop states drawn from fixtures", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium-desktop", "데스크톱 프로젝트에서만 돈다");
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  for (const state of STATES) {
    test(`${state.id} (${state.title})`, async ({ page }) => {
      await mockApi(page, state.reply ?? ok("text"));
      await page.goto("/");
      await expect(
        page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
      ).toBeVisible();
      await state.setup(page);
      await page.evaluate(() => document.fonts.ready);

      const violations = await runAxe(page);
      const outline = await headings(page);
      const problems = headingProblems(outline);
      const known = KNOWN[state.id] ?? [];
      const blocking = violations.filter(
        (item) =>
          (item.impact === "critical" || item.impact === "serious") && !known.includes(item.id),
      );

      if (OUT) {
        fs.mkdirSync(OUT, { recursive: true });
        await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.waitForTimeout(300);
        await page.screenshot({ path: path.join(OUT, `${state.id}.png`), fullPage: true });
        const focus = await page.evaluate(() => {
          const node = document.activeElement;
          return node
            ? `${node.tagName.toLowerCase()}${node.id ? `#${node.id}` : ""} "${(node.textContent ?? "")
                .replace(/\s+/g, " ")
                .trim()
                .slice(0, 40)}"`
            : null;
        });
        fs.writeFileSync(
          path.join(OUT, `${state.id}.json`),
          `${JSON.stringify({ state: state.id, violations, headings: outline, headingProblems: problems, focus }, null, 1)}\n`,
        );
      }
      releaseSearch();
      releaseSearch = () => {};
      if (OUT) return;

      expect(blocking, "axe critical·serious 위반").toEqual([]);
      expect(problems, `제목 구조: ${JSON.stringify(outline)}`).toEqual([]);
    });
  }
});

// ---- 키보드만으로 검색하고 결과를 읽기, 화면 낭독기용 알림(§4-10) ---------------------------------

/** Tab 을 눌러 그 요소까지 간다(마우스 없이). */
async function tabTo(page: Page, target: ReturnType<Page["locator"]>, limit = 80) {
  for (let i = 0; i < limit; i += 1) {
    await page.keyboard.press("Tab");
    if (await target.evaluate((node) => node === document.activeElement).catch(() => false)) return;
  }
  throw new Error("Tab 으로 닿지 못했다");
}
/** 키보드로 간 포커스의 윤곽이 눈에 보이는가(2px 이상의 선). */
const hasFocusRing = (target: ReturnType<Page["locator"]>) =>
  target.evaluate((node) => {
    const style = getComputedStyle(node);
    return style.outlineStyle !== "none" && parseFloat(style.outlineWidth) >= 2;
  });
const focusIsOnBody = (page: Page) => page.evaluate(() => document.activeElement === document.body);
/** 비어 있지 않은 알림(role="status") 글자들 — 같은 말을 두 번 알리지 않는지 본다. */
const statusTexts = (page: Page) =>
  page.evaluate(() =>
    [...document.querySelectorAll('main [role="status"]')]
      .map((node) => (node.textContent ?? "").trim())
      .filter(Boolean),
  );

test.describe("accessibility — keyboard and announcements", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "chromium-desktop", "데스크톱 프로젝트에서만 돈다");
    test.skip(OUT !== null, "캡처할 때는 돌리지 않는다");
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("keyboard only: name, goods, search, result title, expand a card, back to the input screen", async ({
    page,
  }) => {
    await mockApi(page, ok("text"));
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
    ).toBeVisible();
    // 처음 열었을 때는 포커스를 옮기지도 알리지도 않는다
    expect(await focusIsOnBody(page)).toBe(true);
    await expect(page.getByTestId("page-announcement")).toHaveText("");

    // 이름
    const name = page.getByRole("textbox", { name: "상표 이름" });
    await tabTo(page, name);
    expect(await hasFocusRing(name)).toBe(true);
    await page.keyboard.type("블루커피");
    await expect(name).toHaveValue("블루커피");

    // 업종 — 검색칸에 글자를 넣고 화살표·Enter 로 고른다
    const goods = page.getByRole("combobox", { name: "지정상품 검색" });
    await tabTo(page, goods);
    await page.keyboard.type("카페");
    await expect(page.getByRole("option", { name: /카페서비스업/ })).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "카페서비스업 제거" })).toBeVisible();

    // 검색
    const submit = page.getByRole("button", { name: "비슷한 상표 찾아보기" });
    await tabTo(page, submit);
    expect(await hasFocusRing(submit)).toBe(true);
    await page.keyboard.press("Enter");

    // 결과 — 포커스는 결과 화면의 제목으로(윤곽은 그리지 않는다), 알림은 한 번
    const title = page.getByRole("heading", { level: 1, name: "검색 결과" });
    await expect(title).toBeFocused();
    expect(await hasFocusRing(title)).toBe(false);
    await expect(page.getByTestId("page-announcement")).toHaveText(
      "검색 결과가 나왔어요. 전체 등급은 검토 권장이에요.",
    );
    await expect(page.getByTestId("overall-grade")).toHaveText("검토 권장");

    // 후보 카드 펼치기
    const card = page
      .getByRole("region", { name: "유사 상표 후보" })
      .locator(":scope > ul > li")
      .first()
      .getByRole("button")
      .first();
    await tabTo(page, card);
    expect(await hasFocusRing(card)).toBe(true);
    await expect(card).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("Enter");
    await expect(card).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByRole("heading", { level: 4, name: "등급 근거 축" })).toBeVisible();

    // 입력 화면으로 돌아가기 — 포커스는 그 버튼이 가리키는 칸(로고 고르기)으로
    const back = page.getByRole("button", { name: "다른 로고 비교하기" });
    await tabTo(page, back);
    await page.keyboard.press("Enter");
    await expect(
      page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
    ).toBeVisible();
    const picker = page.getByRole("button", { name: /로고 이미지 선택/ });
    await expect(picker).toBeFocused();
    expect(await hasFocusRing(picker)).toBe(true);
    await expect(page.getByTestId("page-announcement")).toHaveText("");
    // 파일 고르기도 키보드로 열린다
    const chooser = page.waitForEvent("filechooser");
    await page.keyboard.press("Enter");
    await chooser;
  });

  test("announcements: searching, result, no candidates and error — and nothing on first load", async ({
    page,
  }) => {
    let release: (reply: SearchReply) => void = () => {};
    await mockApi(page, () => new Promise<SearchReply>((resolve) => (release = resolve)));
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
    ).toBeVisible();
    const line = page.getByTestId("page-announcement");
    await expect(line).toHaveAttribute("role", "status");
    await expect(line).toHaveText("");
    expect(await focusIsOnBody(page)).toBe(true);

    // 검색 중 — "검색하고 있어요" 한 번(검색 중 화면이 같은 뜻을 또 알리지 않는다)
    await fillName(page, "블루커피");
    await search(page);
    await expect(line).toHaveText("검색하고 있어요");
    await expect(page.getByRole("heading", { level: 1, name: "로고를 분석하고 있어요" })).toBeFocused();
    expect(await statusTexts(page)).toEqual(["검색하고 있어요"]);

    // 결과
    release({ status: 200, body: fixture("text") });
    await expect(line).toHaveText("검색 결과가 나왔어요. 전체 등급은 검토 권장이에요.");
    await expect(page.getByRole("heading", { level: 1, name: "검색 결과" })).toBeFocused();
    expect(await statusTexts(page)).toEqual(["검색 결과가 나왔어요. 전체 등급은 검토 권장이에요."]);

    // 입력 화면으로 돌아가 다시 — 후보가 없는 결과
    await page.getByRole("button", { name: "다른 로고 비교하기" }).click();
    await expect(line).toHaveText("");
    await fillName(page, "블루커피");
    await search(page);
    await expect(line).toHaveText("검색하고 있어요");
    release({ status: 200, body: emptyResult() });
    await expect(line).toHaveText("검색 결과가 나왔어요. 비교할 후보가 없어요.");
    await expect(page.getByRole("heading", { level: 1, name: "검색 결과" })).toBeFocused();

    // 오류 — 오류 문장은 바로 알리고(alert) 포커스는 오류 제목으로, 알림 줄은 비운다
    await page.getByRole("button", { name: "다른 로고 비교하기" }).click();
    await fillName(page, "블루커피");
    await search(page);
    release(RATE_LIMITED);
    const title = page.getByRole("heading", { level: 1, name: "검색을 완료하지 못했어요" });
    await expect(title).toBeFocused();
    expect(await hasFocusRing(title)).toBe(false);
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(
      "요청이 너무 많아요. 잠시 후 다시 시도하세요. (1분에 10번까지 검색할 수 있어요)",
    );
    await expect(line).toHaveText("");
    // 입력 확인 후 다시 시도 — 가리키는 칸이 없어 입력 화면의 제목으로
    await page.getByRole("button", { name: "입력 확인 후 다시 시도" }).click();
    await expect(
      page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
    ).toBeFocused();
  });
});
