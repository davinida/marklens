import { expect, test, type Page } from "@playwright/test";

const LOGO_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAACLSURBVHhe7dAxAQAgEIDAD2Mz438I3akAwy2MzLn7zIbBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYfAJdEkoIltljAAAAAElFTkSuQmCC",
  "base64",
);

// API 계약 v2 §2 — 후보 1건(이미지 없음, "안전" 등급)인 최소 유효 응답.
// 요청에 goods_codes 가 있으면 그 축(x4)만 채워서 돌려준다(아래 handler 가 조립).
function buildSearchV2Result(options: { x4?: number | null; nice_classes?: number[] } = {}) {
  const x4 = options.x4 ?? null;
  return {
    api_version: "2026-10-24",
    research_beta: true,
    legal_conclusion: false,
    overall: {
      grade: "안전",
      prob: 0.04,
      caveats: ["이미지가 없어 외관(이미지) 축은 비교하지 않았습니다"],
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
  await expect(page.getByText("이미지가 없어 외관(이미지) 축은 비교하지 않았습니다")).toBeVisible();
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
