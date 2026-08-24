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
  await expectNoHorizontalOverflow(page);
});
