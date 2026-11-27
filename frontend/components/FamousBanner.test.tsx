import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2 from "@/components/ResultViewV2";
import {
  SearchV2ResponseSchema,
  type SearchV2FamousMatch,
  type SearchV2Response,
} from "@/lib/contracts";
import textFixture from "@/test/fixtures/search-v2-text.json";

// 유명 상표 확인 배너(v1.4.7). 시험 자료는 계약 픽스처를 읽어 시험 안에서 필드를 더해 만든다 — 픽스처는
// 실제 엔진으로 다시 만들어질 수 있으니 그 구체 값(위험도·상표명·model_version)에 기대지 않는다.
// 픽스처는 유명 상표 확인을 켠 서버의 응답(확인함·일치 없음)이라, 새 선택 필드를 뺀 것을 바탕으로 쓴다.
const BASE: SearchV2Response = (() => {
  const parsed = SearchV2ResponseSchema.parse(textFixture);
  delete parsed.famous;
  delete parsed.overall.famous_floor;
  for (const candidate of parsed.candidates) delete candidate.famous_brand;
  return parsed;
})();

const DANGER_LEAD =
  "널리 알려진 상표는 업종이 달라도 보호될 수 있어요. 소비자가 관련 있는 곳으로 오해하거나 그 상표의 명성을 해친다고 보면, 등록이 거절되거나 쓰는 것 자체가 분쟁이 될 수 있어요.";
const BODY_DANGER = `${DANGER_LEAD} 다른 이름을 권해요.`;
const BODY_LOGO = `${DANGER_LEAD} 다른 로고를 권해요.`;
const BODY_REVIEW =
  "업종이 달라서 함께 등록될 수도 있지만, 유명한 상표라 문제가 될 수 있어요. 출원 전에 꼭 확인해 보세요.";
const BODY_WEAK =
  "유명한 상표를 떠올리게 하는 이름은 업종이 달라도 문제가 될 수 있어요. 출원 전에 꼭 확인해 보세요.";
const BODY_DESCRIPTIVE =
  "상품을 설명하는 말로 쓰는 건 괜찮을 수 있어요. 다만 가게 이름처럼 눈에 띄게 쓰거나 그 상표의 글자 모양·로고와 비슷하게 쓰면 문제가 될 수 있어요.";
const TITLE_STARBUCKS_STRONG = "널리 알려진 상표 '스타벅스'와 이름이 같거나 거의 같아요";
const REASON_STRONG = "널리 알려진 상표와 같거나 거의 같아서 이 등급으로 봤어요.";
const REASON_WEAK = "널리 알려진 상표와 이름이 닮아서 이 등급으로 봤어요.";
const OVERALL_PRECISION = /'위험'으로 나온 상표 쌍은 검증 데이터 기준 10건 중/;

function famousMatch(overrides: Partial<SearchV2FamousMatch> = {}): SearchV2FamousMatch {
  return {
    brand: "스타벅스",
    level: "강함",
    basis: "이름",
    notation: "스타벅스",
    matched_text: "스타벅스",
    protection: "업종 불문",
    goods_overlap: false,
    floor: "위험",
    logos: [],
    ...overrides,
  };
}

function withFamous(
  matches: SearchV2FamousMatch[],
  options: { status?: string; brandCount?: number } = {},
): SearchV2Response {
  const result = structuredClone(BASE);
  result.famous = {
    status: options.status ?? "checked",
    brand_count: options.brandCount ?? 58,
    matches,
  };
  return result;
}

/** 이름 있는 판단(눈금 표식·위험도 % 가 보이는 계수 집합)의 "위험" 전체 등급으로 맞춘다. */
function namedDanger(result: SearchV2Response, famousFloor?: boolean): SearchV2Response {
  result.overall = { ...result.overall, grade: "위험", prob: 0.61, pattern: "x4" };
  if (famousFloor !== undefined) result.overall.famous_floor = famousFloor;
  return result;
}

function renderResult(result: SearchV2Response) {
  return render(
    <ResultViewV2 result={result} queryPreview={null} queryHasName onReset={vi.fn()} />,
  );
}

describe("유명 상표 확인 배너 — 종류별 문구(글자 그대로)", () => {
  it.each([
    ["이름 강함 · 위험", famousMatch(), TITLE_STARBUCKS_STRONG, BODY_DANGER, "강한 일치"],
    [
      "이름 강함 · 검토 권장(업종이 다른 경우)",
      famousMatch({ floor: "검토 권장", goods_overlap: false }),
      TITLE_STARBUCKS_STRONG,
      BODY_REVIEW,
      "강한 일치",
    ],
    [
      "이름 약함 · 바닥 있음",
      famousMatch({ level: "약함", notation: "스타벅스", matched_text: "스타벅수", floor: "검토 권장" }),
      "널리 알려진 상표 '스타벅스'와 이름이 닮았어요",
      BODY_WEAK,
      "약한 일치",
    ],
    [
      "이름 약함 · 바닥 없음",
      famousMatch({ level: "약함", matched_text: "스타벅수", floor: null }),
      "널리 알려진 상표 '스타벅스'와 이름이 닮았어요",
      BODY_WEAK,
      "약한 일치",
    ],
    [
      "설명적 사용",
      famousMatch({ brand: "토스", level: "설명적 사용", notation: "토스", matched_text: "토스", floor: null }),
      "'토스'는 널리 알려진 상표 이름이기도 해요",
      BODY_DESCRIPTIVE,
      "설명적 사용",
    ],
    [
      "설명적 사용 · 표기 없음이면 브랜드",
      famousMatch({ brand: "토스", level: "설명적 사용", notation: null, matched_text: null, floor: null }),
      "'토스'는 널리 알려진 상표 이름이기도 해요",
      BODY_DESCRIPTIVE,
      "설명적 사용",
    ],
    [
      "로고 강함 · 위험",
      famousMatch({ basis: "로고", notation: null, matched_text: null, floor: "위험" }),
      "널리 알려진 상표 '스타벅스' 쪽의 등록 로고와 같거나 거의 같아요",
      BODY_LOGO,
      "강한 일치",
    ],
    [
      "로고 강함 · 검토 권장도 같은 본문",
      famousMatch({ basis: "로고", notation: null, matched_text: null, floor: "검토 권장" }),
      "널리 알려진 상표 '스타벅스' 쪽의 등록 로고와 같거나 거의 같아요",
      BODY_LOGO,
      "강한 일치",
    ],
    [
      "이미지 속 글자 강함 · 위험",
      famousMatch({ basis: "이미지 속 글자", notation: "STARBUCKS", matched_text: "STARBUCKS COFFEE", floor: "위험" }),
      "이미지 속 글자 'STARBUCKS COFFEE'가 널리 알려진 상표 '스타벅스'와 같거나 거의 같아요",
      BODY_DANGER,
      "강한 일치",
    ],
    [
      "이미지 속 글자 강함 · 검토 권장(글자 없으면 표기)",
      famousMatch({ basis: "이미지 속 글자", notation: "STARBUCKS", matched_text: null, floor: "검토 권장" }),
      "이미지 속 글자 'STARBUCKS'가 널리 알려진 상표 '스타벅스'와 같거나 거의 같아요",
      BODY_REVIEW,
      "강한 일치",
    ],
    [
      "이미지 속 글자 강함 · 글자·표기 모두 없으면 브랜드",
      famousMatch({ basis: "이미지 속 글자", notation: null, matched_text: null, floor: "위험" }),
      "이미지 속 글자 '스타벅스'가 널리 알려진 상표 '스타벅스'와 같거나 거의 같아요",
      BODY_DANGER,
      "강한 일치",
    ],
    [
      "표에 없는 조합: 이름 강함인데 floor 가 null → 둘째 줄 본문",
      famousMatch({ floor: null }),
      TITLE_STARBUCKS_STRONG,
      BODY_REVIEW,
      "강한 일치",
    ],
  ])("%s", (_label, match, title, body, kind) => {
    renderResult(withFamous([match]));
    const heading = screen.getByRole("heading", { level: 2, name: title });
    expect(heading).toBeVisible();
    const banner = screen.getByRole("region", { name: title });
    expect(within(banner).getByText(body)).toBeVisible();
    // 종류가 색만이 아니라 보이는 글로도 드러난다
    expect(within(banner).getByTestId("famous-level")).toHaveTextContent(`유명 상표 확인 · ${kind}`);
    expect(within(banner).getByTestId("famous-level")).toBeVisible();
    expect(within(banner).queryByTestId("famous-second")).toBeNull();
  });

  it("모르는 level 값이면 배너를 그리지 않는다", () => {
    renderResult(withFamous([famousMatch({ level: "보통" })]));
    expect(screen.queryByTestId("famous-banner")).toBeNull();
    expect(screen.queryByText(/널리 알려진 상표/)).toBeNull();
  });

  it("배너는 결과 맨 위에 하나만 그린다", () => {
    const { container } = renderResult(withFamous([famousMatch()]));
    const banners = screen.getAllByTestId("famous-banner");
    expect(banners).toHaveLength(1);
    // 맨 위는 화면에 보이지 않는 결과 제목(h1)이고, 눈에 보이는 것 가운데서는 배너가 맨 위다
    const first = container.firstElementChild?.firstElementChild;
    expect(first?.tagName).toBe("H1");
    expect(first).toHaveClass("sr-only");
    expect(first?.nextElementSibling).toBe(banners[0]);
  });
});

describe("유명 상표 확인 배너 — 조사는 받침에 맞춘다", () => {
  // 문구는 정해진 글자 그대로이고, 브랜드·표기·글자 바로 뒤의 조사만 받침 유무로 고른다
  // (한글 음절이 아니면 결과 화면의 조사 규칙처럼 받침 없는 것으로 본다).
  it.each([
    ["이름 강함 · 받침 있음", famousMatch({ brand: "삼성", notation: "삼성" }), "널리 알려진 상표 '삼성'과 이름이 같거나 거의 같아요"],
    ["이름 약함 · 받침 있음", famousMatch({ brand: "구글", level: "약함", notation: "구글", matched_text: "구굴", floor: "검토 권장" }), "널리 알려진 상표 '구글'과 이름이 닮았어요"],
    ["설명적 사용 · 받침 있음", famousMatch({ brand: "당근", level: "설명적 사용", notation: "당근", matched_text: "당근", floor: null }), "'당근'은 널리 알려진 상표 이름이기도 해요"],
    ["설명적 사용 · 라틴 문자", famousMatch({ brand: "BBQ", level: "설명적 사용", notation: "BBQ", matched_text: "BBQ", floor: null }), "'BBQ'는 널리 알려진 상표 이름이기도 해요"],
    ["이미지 속 글자 · 둘 다 받침 있음", famousMatch({ brand: "쿠팡", basis: "이미지 속 글자", notation: "쿠팡", matched_text: "쿠팡" }), "이미지 속 글자 '쿠팡'이 널리 알려진 상표 '쿠팡'과 같거나 거의 같아요"],
    ["이미지 속 글자 · 받침 없음", famousMatch({ basis: "이미지 속 글자", notation: "STARBUCKS", matched_text: "STARBUCKS COFFEE" }), "이미지 속 글자 'STARBUCKS COFFEE'가 널리 알려진 상표 '스타벅스'와 같거나 거의 같아요"],
  ])("%s", (_label, match, title) => {
    renderResult(withFamous([match]));
    expect(screen.getByRole("heading", { name: title })).toBeVisible();
  });

  it("둘째 브랜드 한 줄도 받침에 맞춘다", () => {
    renderResult(withFamous([famousMatch(), famousMatch({ brand: "던킨", level: "약함", floor: null })]));
    expect(screen.getByTestId("famous-second")).toHaveTextContent("널리 알려진 상표 '던킨'과도 닮았어요.");
  });
});

describe("유명 상표 확인 배너 — 둘째 브랜드 한 줄", () => {
  it.each([
    ["강함", famousMatch({ brand: "STARBUCKS RESERVE", notation: "STARBUCKS RESERVE" }), "널리 알려진 상표 'STARBUCKS RESERVE'와도 같거나 거의 같아요."],
    ["약함", famousMatch({ brand: "스타벅스 리저브", level: "약함", floor: null }), "널리 알려진 상표 '스타벅스 리저브'와도 닮았어요."],
    ["설명적 사용", famousMatch({ brand: "토스", level: "설명적 사용", notation: "토스", floor: null }), "'토스'도 널리 알려진 상표 이름이에요."],
    ["설명적 사용 · 표기 없음", famousMatch({ brand: "토스", level: "설명적 사용", notation: null, floor: null }), "'토스'도 널리 알려진 상표 이름이에요."],
  ])("%s", (_label, second, line) => {
    renderResult(withFamous([famousMatch(), second]));
    const banner = screen.getByRole("region", { name: TITLE_STARBUCKS_STRONG });
    expect(within(banner).getByTestId("famous-second")).toHaveTextContent(line);
    expect(within(banner).getByText(line)).toBeVisible();
    // 둘째 브랜드는 한 줄 — 제목·본문을 따로 그리지 않는다
    expect(screen.getAllByRole("heading", { name: /널리 알려진 상표/ })).toHaveLength(1);
    expect(within(banner).getAllByText(BODY_DANGER)).toHaveLength(1);
  });

  it("셋째 이후 일치와 모르는 level 의 둘째 줄은 그리지 않는다", () => {
    renderResult(
      withFamous([
        famousMatch(),
        famousMatch({ brand: "알 수 없음", level: "보통" }),
        famousMatch({ brand: "셋째 브랜드" }),
      ]),
    );
    expect(screen.getByRole("heading", { name: TITLE_STARBUCKS_STRONG })).toBeVisible();
    expect(screen.queryByTestId("famous-second")).toBeNull();
    expect(screen.queryByText(/셋째 브랜드/)).toBeNull();
  });
});

describe("유명 상표 확인 — 확인하지 못함·일치 없음·없음", () => {
  it("확인하지 못함이면 배너 없이 한 줄만", () => {
    renderResult(withFamous([], { status: "unavailable" }));
    expect(screen.getByTestId("famous-unavailable")).toHaveTextContent("유명 상표 확인을 하지 못했어요.");
    expect(screen.getByText("유명 상표 확인을 하지 못했어요.")).toBeVisible();
    expect(screen.queryByTestId("famous-banner")).toBeNull();
    expect(screen.queryByRole("heading", { name: /널리 알려진 상표/ })).toBeNull();
    expect(screen.queryByText(/목록에 없는 유명 상표도 있어요/)).toBeNull();
  });

  it("famous 가 없으면 아무것도 그리지 않는다 — 확인함 + 일치 없음·famous_floor false 도 같은 화면", () => {
    expect("famous" in BASE).toBe(false);
    const { container: plain, unmount } = renderResult(namedDanger(structuredClone(BASE)));
    // useId 값(렌더마다 늘어나는 _r_…_)만 빼고 견준다
    const html = (element: HTMLElement) => element.innerHTML.replace(/_r_[0-9a-z]+_/g, "_r_id_");
    const plainHtml = html(plain);
    expect(screen.queryByTestId("famous-banner")).toBeNull();
    expect(screen.queryByTestId("famous-unavailable")).toBeNull();
    expect(screen.queryByTestId("famous-floor-reason")).toBeNull();
    expect(screen.queryByTestId("candidate-famous-brand")).toBeNull();
    expect(screen.queryByText(/유명 상표/)).toBeNull();
    // 지금 화면 그대로: 위험도 %·눈금·등급 설명·정밀도 문구
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 61%");
    expect(screen.getByTestId("grade-scale")).toBeInTheDocument();
    expect(screen.getByText("많이 닮은 선행 상표가 있어요")).toBeVisible();
    expect(screen.getByText(OVERALL_PRECISION)).toBeVisible();
    unmount();

    const { container: empty } = renderResult(namedDanger(withFamous([]), false));
    expect(html(empty)).toBe(plainHtml);
  });
});

describe("유명 상표 확인 배너 — 대표 로고 그림", () => {
  const twoLogos = [
    { id: "4020190000001", image_url: "/images/4020190000001.png" },
    { id: "4020190000002", image_url: "/images/4020190000002.png" },
    { id: "4020190000003", image_url: "/images/4020190000003.png" },
  ];

  it("대표 로고를 최대 2장, 대체 글과 함께 후보 카드와 같은 주소 방식으로 그린다", () => {
    renderResult(withFamous([famousMatch({ logos: twoLogos })]));
    const images = screen.getAllByRole("img", { name: "'스타벅스' 대표 로고" });
    expect(images).toHaveLength(2);
    expect(images.map((image) => image.getAttribute("src"))).toEqual([
      "/api/images/4020190000001.png",
      "/api/images/4020190000002.png",
    ]);
  });

  it.each([
    ["logos 빈 배열", []],
    ["image_url null", [{ id: "4020190000001", image_url: null }]],
    ["쓸 수 없는 주소", [{ id: "4020190000001", image_url: "//evil.example/logo.png" }]],
  ])("그림이 없으면(%s) 그림 칸 없이 배너를 그린다", (_label, logos) => {
    renderResult(withFamous([famousMatch({ logos })]));
    expect(screen.getByRole("heading", { name: TITLE_STARBUCKS_STRONG })).toBeVisible();
    expect(screen.queryByRole("img", { name: /대표 로고/ })).toBeNull();
    expect(screen.queryByTestId("famous-logos")).toBeNull();
    // 후보 카드처럼 "이미지 없음" 자리 상자를 남기지 않는다
    const banner = screen.getByTestId("famous-banner");
    expect(within(banner).queryByRole("img")).toBeNull();
  });

  it("그림을 못 받으면 그 그림이 사라지고, 모두 실패하면 그림 칸이 없어진다", () => {
    renderResult(withFamous([famousMatch({ logos: twoLogos.slice(0, 2) })]));
    const [first, second] = screen.getAllByRole("img", { name: "'스타벅스' 대표 로고" });
    fireEvent.error(first);
    expect(screen.getAllByRole("img", { name: "'스타벅스' 대표 로고" })).toEqual([second]);
    fireEvent.error(second);
    expect(screen.queryByRole("img", { name: /대표 로고/ })).toBeNull();
    expect(screen.queryByTestId("famous-logos")).toBeNull();
    const banner = screen.getByTestId("famous-banner");
    expect(within(banner).queryByRole("img")).toBeNull();
    expect(within(banner).getByText(BODY_DANGER)).toBeVisible();
  });
});

describe("유명 상표 확인 배너 — 각주·접근성", () => {
  it("각주의 브랜드 수는 응답의 brand_count", () => {
    renderResult(withFamous([famousMatch()], { brandCount: 61 }));
    expect(screen.getByTestId("famous-footnote")).toHaveTextContent(
      "MarkLens가 정리한 유명 상표 61개 브랜드 기준이에요. 목록에 없는 유명 상표도 있어요.",
    );
    expect(
      screen.getByText("MarkLens가 정리한 유명 상표 61개 브랜드 기준이에요. 목록에 없는 유명 상표도 있어요."),
    ).toBeVisible();
  });

  it("제목 요소(h2 — 결과 화면의 제목 h1 아래, 후보 목록 제목과 같은 단계)·이름 붙은 영역·아이콘은 숨김", () => {
    renderResult(
      withFamous([
        famousMatch({
          logos: [{ id: "4020190000001", image_url: "/images/4020190000001.png" }],
        }),
      ]),
    );
    const title = screen.getByRole("heading", { level: 1, name: "검색 결과" });
    const heading = screen.getByRole("heading", { level: 2, name: TITLE_STARBUCKS_STRONG });
    const banner = screen.getByRole("region", { name: TITLE_STARBUCKS_STRONG });
    expect(banner).toContainElement(heading);
    // 결과가 뜰 때 page.tsx 가 포커스를 옮기는 제목([data-phase-heading])은 결과 화면의 제목 하나
    expect(document.querySelectorAll("[data-phase-heading]")).toHaveLength(1);
    expect(document.querySelector("[data-phase-heading]")).toBe(title);
    expect(title).toHaveAttribute("tabindex", "-1");
    expect(heading).not.toHaveAttribute("tabindex");
    expect(within(banner).getByRole("img", { name: "'스타벅스' 대표 로고" })).toBeVisible();
    for (const svg of banner.querySelectorAll("svg")) {
      expect(svg).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("질의에서 온 글자는 글로만 그린다(HTML 로 해석하지 않는다)", () => {
    const brand = "<img src=x onerror=alert(1)>";
    renderResult(
      withFamous([
        famousMatch({ brand, basis: "이미지 속 글자", notation: null, matched_text: "<b>굵게</b>" }),
      ]),
    );
    const title = `이미지 속 글자 '<b>굵게</b>'가 널리 알려진 상표 '${brand}'와 같거나 거의 같아요`;
    const banner = screen.getByRole("region", { name: title });
    expect(within(banner).getByRole("heading", { name: title })).toBeVisible();
    expect(banner.querySelector("b")).toBeNull();
    expect(banner.querySelector("img")).toBeNull();
  });
});

describe("전체 등급 — 유명 상표 바닥(overall.famous_floor)", () => {
  it("true 면 까닭 한 줄만 보이고 위험도 %·눈금·등급 설명·정밀도 문구는 숨긴다", () => {
    renderResult(namedDanger(withFamous([famousMatch()]), true));
    expect(screen.getByTestId("overall-grade")).toHaveTextContent("위험");
    expect(screen.getByTestId("famous-floor-reason")).toHaveTextContent(REASON_STRONG);
    expect(screen.getByText(REASON_STRONG)).toBeVisible();
    expect(screen.queryByTestId("overall-prob")).toBeNull();
    expect(screen.queryByText(/위험도 \d+%/)).toBeNull();
    expect(screen.queryByTestId("grade-scale")).toBeNull();
    expect(screen.queryByText("많이 닮은 선행 상표가 있어요")).toBeNull();
    expect(screen.queryByText(OVERALL_PRECISION)).toBeNull();
  });

  it("floor 가 전체 등급과 같은 첫 일치가 약함이면 '닮아서' 문구", () => {
    const result = withFamous([
      famousMatch({ floor: null }),
      famousMatch({ brand: "나이키", level: "약함", notation: "NIKE", floor: "검토 권장" }),
    ]);
    result.overall = { ...result.overall, grade: "검토 권장", pattern: "x4", famous_floor: true };
    renderResult(result);
    expect(screen.getByTestId("overall-grade")).toHaveTextContent("검토 권장");
    expect(screen.getByTestId("famous-floor-reason")).toHaveTextContent(REASON_WEAK);
    expect(screen.queryByText("닮은 선행 상표가 있을 수 있어요. 전문가 검토를 권해요")).toBeNull();
    expect(screen.queryByTestId("overall-prob")).toBeNull();
  });

  it("약함 바닥이 위험 등급과 같으면 '닮아서' 문구", () => {
    renderResult(
      namedDanger(withFamous([famousMatch({ level: "약함", floor: "위험" })]), true),
    );
    expect(screen.getByTestId("famous-floor-reason")).toHaveTextContent(REASON_WEAK);
  });

  it("false 면 지금처럼 위험도 %·눈금·등급 설명·정밀도 문구를 그리고 까닭 한 줄은 없다", () => {
    renderResult(namedDanger(withFamous([famousMatch()]), false));
    expect(screen.queryByTestId("famous-floor-reason")).toBeNull();
    expect(screen.getByTestId("overall-prob")).toHaveTextContent("위험도 61%");
    expect(screen.getByTestId("grade-scale")).toBeInTheDocument();
    expect(screen.getByTestId("grade-scale-marker")).toBeInTheDocument();
    expect(screen.getByText("많이 닮은 선행 상표가 있어요")).toBeVisible();
    expect(screen.getByText(OVERALL_PRECISION)).toBeVisible();
    // 배너는 famous_floor 와 상관없이 그린다
    expect(screen.getByRole("heading", { name: TITLE_STARBUCKS_STRONG })).toBeVisible();
  });
});

describe("후보 카드 — 유명 상표 표장", () => {
  it("famous_brand 가 있는 후보에만 '유명 상표 · {브랜드}'", () => {
    const result = structuredClone(BASE);
    expect(result.candidates.length).toBeGreaterThan(1);
    result.candidates[0].famous_brand = "스타벅스";
    renderResult(result);
    const badges = screen.getAllByTestId("candidate-famous-brand");
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveTextContent("유명 상표 · 스타벅스");
    expect(screen.getByText("유명 상표 · 스타벅스")).toBeVisible();
    // 카드 머리(펼치기 버튼) 안의 보조 표시
    expect(screen.getByRole("button", { name: /유명 상표 · 스타벅스/ })).toContainElement(badges[0]);
  });
});
