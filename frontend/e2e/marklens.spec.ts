import { expect, test, type Page } from "@playwright/test";

const LOGO_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAACLSURBVHhe7dAxAQAgEIDAD2Mz438I3akAwy2MzLn7zIbBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYfAJdEkoIltljAAAAAElFTkSuQmCC",
  "base64",
);

// API 계약 v2 §2 — 후보 1건(이미지 없음, "안전" 등급)인 최소 유효 응답.
// 요청에 goods_codes 가 있으면 그 축(x4)만 채워서 돌려준다(아래 handler 가 조립).
function buildSearchV2Result(options: { x4?: number | null; nice_classes?: number[] } = {}) {
  const x4 = options.x4 ?? null;
  // 이름 있는 판단의 계수 집합(계약 v2 §2-2) — 이미지 없음, 상품이 있으면 x4
  const pattern = x4 !== null ? "x4" : "base";
  return {
    api_version: "2026-10-24",
    research_beta: true,
    legal_conclusion: false,
    overall: {
      grade: "안전",
      prob: 0.04,
      pattern,
      caveats: ["이미지가 없어 외관(이미지) 축은 비교하지 않았어요"],
      query_type: { type: "문자", source: "fallback", detail: null, suggested_name: null },
      visual_status: null,
    },
    candidates: [
      {
        id: "4020260012345",
        title: "이모지로고",
        image_url: null,
        type: "결합",
        applicant: "예시 출원인",
        nice_classes: options.nice_classes ?? [43],
        axes: { x1: 0.3, x2_text: 0.2, x2_img: null, x3: null, x4 },
        risk: {
          prob: 0.04,
          grade: "안전",
          contributions: { X1: 0.2, X2: 0.1, X3: 0.0, X4: x4 ? 0.15 : 0.0, 요부: 0.0 },
          missing_adjustment: 0.0,
          figure_caveat: false,
          rule_triggers: [],
          pattern,
        },
        salient: { query_tokens: [], candidate_tokens: [], removed: [] },
        goods: { codes: x4 !== null ? ["G0502"] : [], jaccard: x4 },
      },
    ],
    meta: {
      model_version: "e2e-fixture",
      grade_precision: 0.7,
      thresholds: {
        grade: { 주의: 0.09, "검토 권장": 0.18, 위험: 0.59 },
        nameless: {
          "noname:x2_whole": { 주의: 0.37, "검토 권장": 0.49, 위험: 0.57 },
          "noname:x2_whole+x4": { 주의: 0.29, "검토 권장": 0.44, 위험: 0.79 },
        },
        standalone: { x1: 0.98, x2_text: 0.75, x2_img: null, x3: 0.77, x4: null },
        figure: 0.9,
      },
      pool: { image: 0, phonetic: 1, spelling: 1, semantic: 0, goods: x4 !== null ? 1 : 0, total: 1 },
      elapsed_ms: 10,
    },
    dataset_info: {
      총_상표수: 1,
      출원일자_범위: "E2E fixture",
      데이터_기준: "브라우저 테스트",
      생성일자: "2026-08-14",
    },
    index_size: 1,
    top_k_requested: 5,
    top_k_returned: 1,
  };
}

const SEARCH_V2_RESULT = buildSearchV2Result();

const PHONETIC_RESULT = {
  query: { name: "BBQ", has_pronunciation: true, candidates: ["비비큐"] },
  matches: [
    {
      rank: 1,
      similarity: 1,
      출원번호: "4020260012345",
      상표한글명: "비비큐",
      이미지URL: null,
      출원인: "제너시스비비큐",
      류: [43],
    },
  ],
  searched_count: 1,
  excluded_no_pronunciation: 0,
  dataset_info: {
    총_상표수: 1,
    출원일자_범위: "E2E fixture",
    데이터_기준: "브라우저 테스트",
    생성일자: "2026-08-14",
  },
  params: { top_k: 5, min_similarity: 0.5 },
  axis: "X1",
  note: "호칭(발음) 유사도만 반영한 참고 정보",
};

const SEMANTIC_RESULT = {
  query: { name: "BBQ", has_meaning: true, text: "bbq" },
  matches: [
    {
      rank: 1,
      score: 0.82,
      출원번호: "4020260012345",
      상표한글명: "비비큐",
      이미지URL: null,
      출원인: "제너시스비비큐",
      류: [43],
    },
  ],
  searched_count: 1,
  excluded_no_meaning: 0,
  dataset_info: {
    총_상표수: 1,
    출원일자_범위: "E2E fixture",
    데이터_기준: "브라우저 테스트",
    생성일자: "2026-08-14",
  },
  params: { top_k: 5, min_score: 0.55 },
  threshold: 0.55,
  axis: "X3",
  note: "관념(의미) 유사도만 반영한 참고 정보",
  model: "e2e-fixture",
};

const GOODS_SEARCH_RESULT = {
  query: "커피",
  matches: [
    { name: "커피", nice_class: 30, similarity_codes: ["G0502"], matched_alias: null },
    {
      name: "커피전문점업",
      nice_class: 43,
      similarity_codes: ["S120602", "G0502"],
      matched_alias: null,
    },
  ],
  total: 2,
  offset: 0,
  source: "E2E fixture",
};

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

const NAME_CHECK_RESULT = {
  query: "BBQ",
  total_found: 3,
  scanned_count: 3,
  registered_count: 2,
  exact_registered_count: 1,
  exact_title_count: 2,
  status_counts: { "등록": 2, "소멸": 1 },
  candidates: [
    {
      application_number: "4020260012345",
      registration_number: "4012345670000",
      application_date: "20260101",
      registration_date: "20260701",
      title: "BBQ",
      status: "등록",
      mark_type: "일반상표",
      applicant: "제너시스비비큐",
      right_holder: "제너시스비비큐",
      nice_classes: ["29", "43"],
      vienna_codes: ["27.05.01"],
      similarity_codes: ["G0301"],
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
  message: "동일 명칭의 선행 등록상표 1건이 존재합니다.",
};

async function expectNoHorizontalOverflow(page: Page) {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth,
    ),
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
}

async function chooseLogo(page: Page) {
  const chooserPromise = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /로고 이미지 선택/ }).click();
  const chooser = await chooserPromise;
  await chooser.setFiles({
    name: "marklens-e2e.png",
    mimeType: "image/png",
    buffer: LOGO_PNG,
  });
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "어떤 로고를 등록하고 싶으세요?" }),
  ).toBeVisible();
  await expect(page.locator("body")).toContainText("MarkLens");
  await expect(page.locator("main")).not.toBeEmpty();
  await expectNoHorizontalOverflow(page);
});

test("home and crop cancellation stay usable without viewport overflow", async ({
  page,
}) => {
  await chooseLogo(page);

  const dialog = page.getByRole("dialog", { name: "분석할 로고 영역 선택" });
  await expect(dialog).toBeVisible();
  const viewport = page.viewportSize();
  const box = await dialog.boundingBox();
  expect(viewport).not.toBeNull();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height + 1);
  const dialogDimensions = await dialog.evaluate((element) => ({
    clientWidth: element.clientWidth,
    scrollWidth: element.scrollWidth,
  }));
  expect(dialogDimensions.scrollWidth).toBeLessThanOrEqual(
    dialogDimensions.clientWidth + 1,
  );
  await expectNoHorizontalOverflow(page);

  const cancel = dialog.getByRole("button", { name: "취소" });
  await cancel.scrollIntoViewIfNeeded();
  await expect(cancel).toBeVisible();
  await cancel.click();

  await expect(dialog).toBeHidden();
  await expect(
    page.getByRole("button", { name: /로고 이미지 선택/ }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("cropped upload renders a mocked same-origin search result", async ({ page }) => {
  let searchRequest: { contentType: string; token: string; bodyBytes: number } | null =
    null;
  await page.route("**/api/search/v2*", async (route) => {
    const request = route.request();
    searchRequest = {
      contentType: request.headers()["content-type"] ?? "",
      token: request.headers()["x-turnstile-token"] ?? "",
      bodyBytes: request.postDataBuffer()?.byteLength ?? 0,
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "x-request-id": "e2e-search-1" },
      body: JSON.stringify(SEARCH_V2_RESULT),
    });
  });

  await chooseLogo(page);
  const dialog = page.getByRole("dialog", { name: "분석할 로고 영역 선택" });
  const useFullImage = dialog.getByRole("button", { name: "전체 이미지 사용" });
  await expect(useFullImage).toBeEnabled();
  await useFullImage.click();

  await expect(dialog).toBeHidden();
  await expect(page.getByRole("img", { name: "선택한 로고 미리보기" })).toBeVisible();
  const submit = page.getByRole("button", { name: "비슷한 상표 찾아보기" });
  await expect(submit).toBeEnabled();
  await submit.click();

  await expect(page.getByTestId("overall-grade")).toHaveText("안전");
  await expect(
    page.getByRole("img", { name: "상표 이미지 없음" }).first(),
  ).toBeVisible();
  await expect(page.getByText("이미지가 없어 외관(이미지) 축은 비교하지 않았어요")).toBeVisible();
  expect(searchRequest).toEqual({
    contentType: expect.stringContaining("multipart/form-data; boundary="),
    token: "dev-bypass",
    bodyBytes: expect.any(Number),
  });
  expect(searchRequest!.bodyBytes).toBeGreaterThan(0);
  await expectNoHorizontalOverflow(page);
});

test("name evidence opens and remains visible in the result dashboard", async ({
  page,
}) => {
  await page.route("**/api/name-check", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(NAME_CHECK_RESULT),
    });
  });
  await page.route("**/api/phonetic-search", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(PHONETIC_RESULT),
    });
  });
  await page.route("**/api/semantic-search", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEMANTIC_RESULT),
    });
  });
  await page.route("**/api/search/v2*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEARCH_V2_RESULT),
    });
  });

  await page.getByRole("textbox", { name: "상표 이름" }).fill("BBQ");
  await page.getByRole("button", { name: "이름 확인" }).click();
  await expect(page.getByText("동일 명칭 등록", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /BBQ/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "발음(호칭)이 비슷한 등록상표" }),
  ).toBeVisible();
  await expect(page.getByText("X1 호칭 유사도 · DB 1건 대상 · 참고 정보")).toBeVisible();
  await expect(page.getByRole("heading", { name: "관념 유사 후보" })).toBeVisible();
  await expect(page.getByText("X3 관념 유사도 · DB 1건 대상 · 참고 정보")).toBeVisible();
  await expect(page.getByText("82%")).toBeVisible();

  await page.getByRole("button", { name: /BBQ/ }).click();
  const kiprisLink = page.getByRole("link", { name: /KIPRIS에서 원문 확인/ });
  await expect(kiprisLink).toHaveAttribute("target", "_blank");
  await expect(kiprisLink).toHaveAttribute("href", /queryText=4020260012345/);

  await chooseLogo(page);
  await page
    .getByRole("dialog", { name: "분석할 로고 영역 선택" })
    .getByRole("button", { name: "전체 이미지 사용" })
    .click();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  // 결과 화면은 v2(API 계약 v2) — 이름 확인·발음·관념 근거는 입력 화면(위에서 이미 확인)에만
  // 남고, 결과 화면은 후보마다 호칭(X1) 축 값으로 같은 이름이 반영됐음을 보여준다.
  await expect(page.getByTestId("overall-grade")).toHaveText("안전");
  await expect(page.getByText("호칭 30%")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("selected goods survive the search and appear in the result summary", async ({ page }) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "커피"
          ? GOODS_SEARCH_RESULT
          : url.searchParams.get("q") === "카페"
            ? CAFE_PRESET_RESULT
            : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  await page.route("**/api/goods/classes", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GOODS_CLASSES_RESULT),
    });
  });
  // 선택한 지정상품의 유사군 코드(G0502, S120602)가 /search/v2 요청에 실려가는지, 응답의
  // X4(상품) 축이 결과 화면에 반영되는지 확인한다 — v1 의 "[data-goods-summary]" 요약은
  // v2 결과 화면에 없고, 대신 후보의 상품 축 값·유사군으로 드러난다.
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildSearchV2Result({ x4: 0.5, nice_classes: [43] })),
    });
  });

  const picker = page.getByRole("combobox", { name: "지정상품 검색" });
  await picker.fill("커피");
  await page.getByRole("option", { name: /^커피 제30류/ }).click();
  await page.getByRole("option", { name: /커피전문점업/ }).click();
  await expect(page.getByRole("button", { name: "커피 제거" })).toBeVisible();
  await expect(page.getByRole("button", { name: "커피전문점업 제거" })).toBeVisible();
  await expect(page.getByText("선택 2개")).toBeVisible();
  await expect(page.getByText("유사군 2개")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await chooseLogo(page);
  await page
    .getByRole("dialog", { name: "분석할 로고 영역 선택" })
    .getByRole("button", { name: "전체 이미지 사용" })
    .click();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  await expect(page.getByTestId("overall-grade")).toHaveText("안전");
  expect(searchBody).toContain("G0502");
  expect(searchBody).toContain("S120602");
  await expect(page.getByText("상품 50%")).toBeVisible();
  await page.getByRole("button").filter({ hasText: "이모지로고" }).click();
  await expect(page.getByText(/지정상품 유사군 G0502/)).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("a business preset adds three goods that show up in the result summary", async ({ page }) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "카페"
          ? CAFE_PRESET_RESULT
          : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildSearchV2Result({ x4: 0.75, nice_classes: [43] })),
    });
  });

  await page.getByRole("combobox", { name: "지정상품 검색" }).fill("카페");
  const card = page.getByRole("region", { name: "카페 업종 세트" });
  await expect(card).toBeVisible();
  // 카드 등장 애니메이션(.rise transform)이 켜진 상태에서도 드롭다운이 다음 카드 위에 그려진다
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect
    .poll(() =>
      page.evaluate(() => {
        const section = document.querySelector('section[aria-labelledby="goods-title"]')!;
        const dropdown = document.querySelector('section[aria-label="카페 업종 세트"]')!
          .parentElement!;
        dropdown.scrollIntoView({ block: "start" });
        window.scrollBy(0, -64); // 고정 헤더(h-14) 아래로
        const box = dropdown.getBoundingClientRect();
        const hit = document.elementFromPoint(box.x + box.width / 2, box.y + 56);
        return {
          animated: getComputedStyle(section).transform !== "none",
          dropdownOnTop: !!hit && hit.closest("[data-goods-picker]") !== null,
        };
      }),
    )
    .toEqual({ animated: true, dropdownOnTop: true });
  await card.getByRole("button", { name: "3개 모두 추가" }).click();
  for (const name of ["커피전문점업", "커피", "커피 소매업"]) {
    await expect(page.getByRole("button", { name: `${name} 제거` })).toBeVisible();
  }
  await expect(page.getByText("선택 3개")).toBeVisible();
  await expect(page.getByText("유사군 4개")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await chooseLogo(page);
  await page
    .getByRole("dialog", { name: "분석할 로고 영역 선택" })
    .getByRole("button", { name: "전체 이미지 사용" })
    .click();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  await expect(page.getByTestId("overall-grade")).toHaveText("안전");
  for (const code of ["G0301", "G0502", "S120602", "S2005"]) {
    expect(searchBody).toContain(code);
  }
  await expect(page.getByText("상품 75%")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

// 유명 상표 확인(v1.4.7) — 기존 모의 응답에 선택 필드(famous·overall.famous_floor)를 더한다.
const CLOTHING_GOODS_RESULT = {
  query: "의류",
  matches: [{ name: "의류", nice_class: 25, similarity_codes: ["G4503"], matched_alias: null }],
  total: 1,
  offset: 0,
  source: "E2E fixture",
};

function buildFamousSearchV2Result() {
  const result = buildSearchV2Result({ x4: 0, nice_classes: [43] });
  return {
    ...result,
    overall: { ...result.overall, grade: "위험", famous_floor: true },
    famous: {
      status: "checked",
      brand_count: 58,
      matches: [
        {
          brand: "스타벅스",
          level: "강함",
          basis: "이름",
          notation: "스타벅스",
          matched_text: "스타벅스",
          protection: "업종 불문",
          goods_overlap: false,
          floor: "위험",
          logos: [{ id: "4020190000001", image_url: "/images/4020190000001.png" }],
        },
      ],
    },
  };
}

test("a famous mark name with clothing goods shows the famous banner and the floor reason", async ({
  page,
}) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "의류"
          ? CLOTHING_GOODS_RESULT
          : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  await page.route("**/api/goods/classes", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GOODS_CLASSES_RESULT),
    });
  });
  await page.route("**/api/images/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: LOGO_PNG });
  });
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildFamousSearchV2Result()),
    });
  });

  await page.getByRole("textbox", { name: "상표 이름" }).fill("스타벅스");
  await page.getByRole("combobox", { name: "지정상품 검색" }).fill("의류");
  await page.getByRole("option", { name: /^의류 제25류/ }).click();
  await expect(page.getByRole("button", { name: "의류 제거" })).toBeVisible();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  const title = "널리 알려진 상표 '스타벅스'와 이름이 같거나 거의 같아요";
  const banner = page.getByRole("region", { name: title });
  await expect(banner.getByRole("heading", { level: 2, name: title })).toBeVisible();
  await expect(
    banner.getByText(
      "MarkLens가 정리한 유명 상표 58개 브랜드 기준이에요. 목록에 없는 유명 상표도 있어요.",
    ),
  ).toBeVisible();
  await expect(banner.getByRole("img", { name: "'스타벅스' 대표 로고" })).toBeVisible();
  await expect(page.getByTestId("overall-grade")).toHaveText("위험");
  await expect(page.getByTestId("famous-floor-reason")).toHaveText(
    "널리 알려진 상표와 같거나 거의 같아서 이 등급으로 봤어요.",
  );
  await expect(page.getByTestId("overall-prob")).toHaveCount(0);
  expect(searchBody).toContain("스타벅스");
  expect(searchBody).toContain("G4503");
  await expectNoHorizontalOverflow(page);
});

// 설명적 이름 안내(계약 v2 §2-7·§4-7) — 기존 모의 응답에 선택 필드 name_words 를 더한다.
function buildDescriptiveSearchV2Result() {
  const result = buildSearchV2Result({ x4: 0.75, nice_classes: [43] });
  return {
    ...result,
    overall: { ...result.overall, grade: "주의", prob: 0.41 },
    name_words: {
      generic: "all",
      words: [
        { word: "맛있는", distinctive: false, category: "성질·품질", reason: "3호 기술적 표장:품질(류 29,30,43)" },
        { word: "커피", distinctive: false, category: "상품 이름", reason: "3호 기술적 표장:원재료(류 30,35,43)·1호 보통명칭" },
        { word: "전문점", distinctive: false, category: "성질·품질", reason: "3호 기술적 표장:용도(류 35,43)" },
      ],
      more: 0,
      more_generic: 0,
    },
  };
}

test("a name made only of descriptive words shows the notice and lets the user try another name", async ({
  page,
}) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "카페"
          ? CAFE_PRESET_RESULT
          : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildDescriptiveSearchV2Result()),
    });
  });

  const nameField = page.getByRole("textbox", { name: "상표 이름" });
  await nameField.fill("맛있는 커피 전문점");
  await page.getByRole("combobox", { name: "지정상품 검색" }).fill("카페");
  await page
    .getByRole("region", { name: "카페 업종 세트" })
    .getByRole("button", { name: "3개 모두 추가" })
    .click();
  await expect(page.getByText("선택 3개")).toBeVisible();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  const title = "이 이름은 상표로 등록받기 어려울 수 있어요";
  const notice = page.getByRole("region", { name: title });
  const heading = notice.getByRole("heading", { level: 2, name: title });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused(); // 결과가 뜨면 맨 위 안내의 제목이 읽힌다
  await expect(
    notice.getByText("'맛있는 커피 전문점'은 모두 상품을 설명하거나 누구나 쓰는 말이에요."),
  ).toBeVisible();
  await expect(notice.getByTestId("descriptive-words").getByRole("listitem")).toHaveText([
    "맛있는 — 맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
    "커피 — 파는 상품이나 서비스의 이름 그 자체예요",
    "전문점 — 맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
  ]);
  await expect(notice.getByText("예: '○○ 커피'처럼요.")).toBeVisible();
  await expect(
    notice.getByText(
      "최종 판단은 특허청 심사에서 정해져요. 오래 써서 많은 사람이 알아보는 이름은 예외가 될 수 있어요.",
    ),
  ).toBeVisible();
  // 안내는 전체 등급 위에 있고, 등급은 그대로다
  await expect(page.getByTestId("overall-grade")).toHaveText("주의");
  await expect(page.getByTestId("descriptive-whole-name")).toHaveText(
    "설명하는 말로만 된 이름이라, 아래는 이름 전체를 견준 결과예요.",
  );
  expect(searchBody).toContain("맛있는 커피 전문점");
  expect(searchBody).toContain("S120602");
  await expectNoHorizontalOverflow(page);

  // "다른 이름으로 다시 확인하기" — 입력은 그대로 둔 채 입력 화면으로 돌아가 이름 칸을 고른다
  await notice.getByRole("button", { name: "다른 이름으로 다시 확인하기" }).click();
  await expect(nameField).toBeFocused();
  await expect(nameField).toHaveValue("맛있는 커피 전문점");
  await expect(page.getByText("선택 3개")).toBeVisible();
  await nameField.pressSequentially("몬테로사");
  await expect(nameField).toHaveValue("몬테로사"); // 전체 선택돼 있어 바로 새 이름으로 바뀐다
});

// 유명 상표 배너가 이름 쪽의 강한 일치로 뜨면 설명적 이름 안내를 그리지 않는다(계약 v2 §4-7). 파리바게트는
// 엔진이 파리(지역 이름)·바게트(상품 이름)로 나눠 모든 낱말이 식별력 없는 말이지만, 배너만 보인다.
function buildFamousDescriptiveSearchV2Result() {
  const result = buildSearchV2Result({ x4: null, nice_classes: [30] });
  return {
    ...result,
    overall: { ...result.overall, grade: "위험", famous_floor: true },
    famous: {
      status: "checked",
      brand_count: 58,
      matches: [
        {
          brand: "파리바게뜨",
          level: "강함",
          basis: "이름",
          notation: "파리바게뜨",
          matched_text: "파리바게트",
          protection: "같은·가까운 업종 중심",
          goods_overlap: null,
          floor: "위험",
          logos: [],
        },
      ],
    },
    name_words: {
      generic: "all",
      words: [
        { word: "파리", distinctive: false, category: "지역 이름", reason: "4호 지명" },
        { word: "바게트", distinctive: false, category: "상품 이름", reason: "1호 보통명칭" },
      ],
      more: 0,
      more_generic: 0,
    },
  };
}

test("a strong famous-name match shows only the famous banner, not the descriptive-name notice", async ({
  page,
}) => {
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildFamousDescriptiveSearchV2Result()),
    });
  });

  await page.getByRole("textbox", { name: "상표 이름" }).fill("파리바게트");
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  const title = "널리 알려진 상표 '파리바게뜨'와 이름이 같거나 거의 같아요";
  const banner = page.getByRole("region", { name: title });
  const heading = banner.getByRole("heading", { level: 2, name: title });
  await expect(heading).toBeVisible();
  await expect(heading).toBeFocused(); // 결과가 뜨면 배너의 제목이 읽힌다
  await expect(page.getByTestId("overall-grade")).toHaveText("위험");
  await expect(page.getByTestId("famous-floor-reason")).toHaveText(
    "널리 알려진 상표와 같거나 거의 같아서 이 등급으로 봤어요.",
  );
  // 큰 안내도 작은 안내도, 전체 등급 옆의 "이름 전체를 견준 결과" 한 줄도 없다
  await expect(page.getByTestId("descriptive-notice")).toHaveCount(0);
  await expect(page.getByTestId("descriptive-whole-name")).toHaveCount(0);
  await expect(page.getByText("누구나 쓰는 말")).toHaveCount(0);
  expect(searchBody).toContain("파리바게트");
  await expectNoHorizontalOverflow(page);
});

// 업종은 다르지만 표장이 닮은 후보(계약 v2 §2-8·§4-8) — 기존 모의 응답에 선택 필드 cross_goods(후보)와
// cross_goods_more(처음 보이는 범위 밖의 후보)를 더한다.
function buildCrossGoodsSearchV2Result() {
  const result = buildSearchV2Result({ x4: 0, nice_classes: [25] });
  const [base] = result.candidates;
  const lookalike = {
    ...base,
    title: "BLU hands",
    risk: { ...base.risk, grade: "검토 권장", prob: 0.52, rule_triggers: ["standalone_x1"] },
    cross_goods: { differs: true, grade_without_goods: "검토 권장", flagged: true },
  };
  const sameGoods = {
    ...base,
    id: "4020260012346",
    title: "내림 커피",
    nice_classes: [43],
    axes: { ...base.axes, x4: 0.6 },
    goods: { codes: ["G0502"], jaccard: 0.6 },
    cross_goods: { differs: false, grade_without_goods: null, flagged: false },
  };
  const outsideFamous = {
    ...lookalike,
    id: "4020260012347",
    title: "STARBUCKS COFFEE",
    famous_brand: "스타벅스",
    cross_goods: { differs: true, grade_without_goods: "위험", flagged: true },
  };
  const outsidePlain = { ...lookalike, id: "4020260012348", title: "BLUE HANDS" };
  return {
    ...result,
    overall: { ...result.overall, grade: "검토 권장", prob: 0.52 },
    candidates: [lookalike, sameGoods],
    cross_goods_more: { count: 2, candidates: [outsideFamous, outsidePlain] },
    top_k_returned: 2,
  };
}

test("a look-alike mark in a different business is marked on its card, next to the overall grade and in a folded section", async ({
  page,
}) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "카페"
          ? CAFE_PRESET_RESULT
          : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  let searchBody = "";
  await page.route("**/api/search/v2*", async (route) => {
    searchBody = route.request().postData() ?? "";
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(buildCrossGoodsSearchV2Result()),
    });
  });

  await page.getByRole("textbox", { name: "상표 이름" }).fill("블루핸즈");
  await page.getByRole("combobox", { name: "지정상품 검색" }).fill("카페");
  await page
    .getByRole("region", { name: "카페 업종 세트" })
    .getByRole("button", { name: "3개 모두 추가" })
    .click();
  await expect(page.getByText("선택 3개")).toBeVisible();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();

  // 전체 등급 옆 한 줄 — 가장 위 후보가 다른 업종의 닮은 상표
  await expect(page.getByTestId("overall-grade")).toHaveText("검토 권장");
  await expect(page.getByTestId("cross-goods-overall")).toHaveText(
    "가장 닮은 상표가 다른 업종에 있어요. 업종이 다르면 함께 등록될 수도 있어요.",
  );
  // 후보 카드 — 정의에 맞는 후보에만 "업종 다름" 표시와 설명 한 줄
  const list = page.getByRole("region", { name: "유사 상표 후보" });
  const first = list.locator(":scope > ul > li").nth(0);
  const second = list.locator(":scope > ul > li").nth(1);
  await expect(first.getByTestId("candidate-cross-goods")).toHaveText("업종 다름");
  await expect(first.getByTestId("candidate-cross-goods-line")).toHaveText(
    "표장은 닮았지만 업종이 달라요. 보통은 함께 등록될 수 있어요. 다만 나중에 이 업종으로 넓히면 문제가 될 수 있어요.",
  );
  await expect(second.getByTestId("candidate-cross-goods")).toHaveCount(0);
  await expect(list.getByText("업종 다름")).toHaveCount(1);

  // 목록 아래 접힌 칸 — 처음 보이는 범위 밖의 후보
  const title = "업종은 다르지만 표장이 닮은 상표 2건";
  const more = page.getByRole("region", { name: title });
  const toggle = more.getByRole("button", { name: title });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await expect(more.getByText("STARBUCKS COFFEE")).toBeHidden();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  const outside = more.getByTestId("cross-goods-more-panel").locator(":scope > ul > li");
  await expect(outside).toHaveCount(2);
  await expect(outside.nth(0).getByText("STARBUCKS COFFEE")).toBeVisible();
  await expect(outside.nth(0).getByTestId("candidate-cross-goods-line")).toHaveText(
    "업종은 다르지만 널리 알려진 상표라 문제가 될 수 있어요.",
  );
  await expect(outside.nth(1).getByTestId("candidate-cross-goods")).toHaveText("업종 다름");
  await expectNoHorizontalOverflow(page);
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(searchBody).toContain("블루핸즈");
  expect(searchBody).toContain("S120602");
});

test("a logo-only search invites the user to add the name read from the logo, keeping the logo and goods", async ({
  page,
}) => {
  await page.route("**/api/goods/search?*", async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        url.searchParams.get("q") === "커피"
          ? GOODS_SEARCH_RESULT
          : { query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 },
      ),
    });
  });
  await page.route("**/api/goods/classes", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(GOODS_CLASSES_RESULT),
    });
  });
  // 로고만 넣은 검색의 응답 — 로고에서 읽은 글자(suggested_name)와 사진 안내가 주의 문구로 함께 온다.
  const nameSuggested =
    "이미지에서 'BLUhands'를 읽었어요 — 상표명으로 넣으면 호칭·철자·관념도 비교해요";
  const photo = "사진으로 보여요 — 로고 파일을 올리면 외관 비교가 더 정확해요";
  const base = buildSearchV2Result({ x4: 0.5, nice_classes: [43] });
  const result = {
    ...base,
    overall: {
      ...base.overall,
      pattern: "noname:x2_whole+x4",
      caveats: ["상표명이 없어 호칭·철자·관념 축은 비교하지 않았어요", nameSuggested, photo],
      query_type: {
        type: "결합-도형요부",
        source: "ocr",
        detail: { text_ratio: 0.2, fig_ratio: 0.5 },
        suggested_name: "BLUhands",
      },
      visual_status: "WEAK_MATCH",
    },
  };
  let searches = 0;
  await page.route("**/api/search/v2*", async (route) => {
    searches += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(result),
    });
  });

  const picker = page.getByRole("combobox", { name: "지정상품 검색" });
  await picker.fill("커피");
  await page.getByRole("option", { name: /^커피 제30류/ }).click();
  await chooseLogo(page);
  await page
    .getByRole("dialog", { name: "분석할 로고 영역 선택" })
    .getByRole("button", { name: "전체 이미지 사용" })
    .click();
  await page.getByRole("button", { name: "비슷한 상표 찾아보기" }).click();
  await expect(page.getByTestId("overall-grade")).toHaveText("안전");

  // 맨 위 안내: 사진 안내 → 상표명 입력 안내(A형), 그 아래 검색 내용 한 줄 → 전체 등급
  const notice = page.getByTestId("logo-only-notice");
  await expect(notice).toHaveAttribute("data-kind", "read");
  await expect(notice.getByTestId("logo-only-line")).toHaveText(
    "로고에서 'BLUhands'를 읽었어요. 지금은 로고 모양만 비교했어요. 이름까지 넣으면 이름이 닮은 상표도 찾을 수 있어요.",
  );
  await expect(page.getByTestId("photo-notice")).toHaveText(photo);
  await expect(page.getByText(photo)).toHaveCount(1);
  // 같은 내용의 기존 줄은 보이지 않는다
  await expect(page.getByRole("button", { name: /상표명으로 넣기/ })).toHaveCount(0);
  await expect(page.getByText(nameSuggested)).toHaveCount(0);
  await expect(page.getByText("상표명이 없어 호칭·철자·관념 축은 비교하지 않았어요")).toBeVisible();
  const order = await page.evaluate(() => {
    const top = (id: string) =>
      document.querySelector(`[data-testid="${id}"]`)!.getBoundingClientRect().top;
    return ["photo-notice", "logo-only-notice", "query-summary", "overall-grade"].map(top);
  });
  expect([...order].sort((a, b) => a - b)).toEqual(order);
  const summary = page.getByTestId("query-summary");
  await expect(summary.getByTestId("query-summary-name")).toHaveText("이름 없음");
  await expect(summary.getByRole("img", { name: "검색한 로고" })).toBeVisible();
  await expect(summary.getByTestId("query-summary-goods")).toHaveText("커피");
  await expect(page.getByTestId("reference-note")).toHaveText(
    "참고용 결과예요. 법적 판단이 아니에요.",
  );
  await expectNoHorizontalOverflow(page);

  // 버튼 — 입력 화면으로 돌아가 이름 칸에 읽은 글자를 채우고 포커스, 로고·업종은 그대로, 다시 검색하지 않음
  await notice.getByRole("button", { name: "이 이름을 넣고 다시 확인하기" }).click();
  const nameInput = page.getByRole("textbox", { name: "상표 이름" });
  await expect(nameInput).toHaveValue("BLUhands");
  await expect(nameInput).toBeFocused();
  await expect(page.getByRole("img", { name: "선택한 로고 미리보기" })).toBeVisible();
  await expect(page.getByRole("button", { name: "커피 제거" })).toBeVisible();
  await expect(
    page.getByText("이미지에서 읽은 글자예요 — 틀린 부분이 있으면 고쳐 주세요."),
  ).toBeVisible();
  expect(searches).toBe(1);
  await expectNoHorizontalOverflow(page);
});
