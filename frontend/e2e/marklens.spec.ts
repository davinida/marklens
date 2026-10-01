import { expect, test, type Page } from "@playwright/test";

const LOGO_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAACLSURBVHhe7dAxAQAgEIDAD2Mz438I3akAwy2MzLn7zIbBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYNIDBpgEMNg1gsGkAg00DGGwawGDTAAabBjDYfAJdEkoIltljAAAAAElFTkSuQmCC",
  "base64",
);

const SEARCH_RESULT = {
  grade: {
    status_code: "NO_CLOSE_MATCH",
    status_name: "가까운 시각 후보 미확인",
    uncertain: false,
    uncertainty_reasons: [],
    scored_candidate_count: 1,
    threshold_version: "e2e-fixture-v1",
    scope: "visual_similarity_only",
    calibrated: false,
    legal_conclusion: false,
    grade_code: "LOW",
    grade_name: "가까운 후보 미확인",
    message: "테스트 데이터 범위에서 가까운 시각 후보를 찾지 못했어요.",
    top1_similarity: 0.2,
    separability_a: 0.1,
    separability_b: 0.1,
    warnings: [],
  },
  matches: [
    {
      rank: 1,
      similarity: 0.2,
      이미지파일: null,
      이미지URL: null,
      trademark: null,
    },
  ],
  dataset_info: {
    총_상표수: 1,
    출원일자_범위: "E2E fixture",
    데이터_기준: "브라우저 테스트",
    생성일자: "2026-08-14",
  },
  index_size: 1,
  top_k_requested: 5,
  top_k_returned: 1,
  scoring_k: 1,
  api_version: "e2e",
  research_beta: true,
};

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
  await page.route("**/api/search?*", async (route) => {
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
      body: JSON.stringify(SEARCH_RESULT),
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

  await expect(
    page.getByRole("heading", { name: "가까운 시각 후보를 찾지 못했어요" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "상표 이미지 없음" }).first(),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "분석 근거 대시보드" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "분석 범위" })).toBeVisible();
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
  await page.route("**/api/search?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEARCH_RESULT),
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

  await expect(page.getByRole("heading", { name: "명칭 검색 근거" })).toBeVisible();
  await expect(page.getByRole("button", { name: /BBQ/ })).toBeVisible();
  await expect(page.getByText("별도 조회됨")).toBeVisible();
  await expect(page.getByText("동일 명칭 등록상표 1건 확인")).toBeVisible();
  await expect(
    page.locator("[data-name-evidence] + [data-visual-candidates]"),
  ).toBeVisible();
  await expect(page.locator("[data-phonetic-evidence]")).toBeVisible();
  await expect(page.locator("[data-semantic-evidence]")).toBeVisible();
  await expect(page.getByText("호칭·관념 조회됨")).toBeVisible();
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
  await page.route("**/api/search?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEARCH_RESULT),
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

  await expect(
    page.getByRole("heading", { name: "가까운 시각 후보를 찾지 못했어요" }),
  ).toBeVisible();
  await expect(page.locator("[data-goods-summary]")).toContainText(
    "선택한 지정상품: 커피, 커피전문점업 (유사군 2개)",
  );
  await expect(page.getByText("지정상품 2개 선택(유사군 2개) · 검색 반영 전")).toBeVisible();
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
  await page.route("**/api/search?*", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(SEARCH_RESULT),
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

  await expect(page.locator("[data-goods-summary]")).toContainText(
    "선택한 지정상품: 커피전문점업, 커피, 커피 소매업 (유사군 4개)",
  );
  await expectNoHorizontalOverflow(page);
});
