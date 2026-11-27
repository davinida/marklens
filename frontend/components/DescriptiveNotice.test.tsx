import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { famousBannerState } from "@/components/FamousBanner";
import ResultViewV2 from "@/components/ResultViewV2";
import {
  SearchV2ResponseSchema,
  type SearchV2FamousMatch,
  type SearchV2NameWord,
  type SearchV2NameWords,
  type SearchV2Response,
} from "@/lib/contracts";
import {
  BIG_NOTICE_CATEGORIES,
  CATEGORY_OTHER_TEXT,
  CATEGORY_TEXT,
  NOTICE_TEXT,
  allSmallLine,
  bigLine,
  categoryText,
  descriptiveNoticeKind,
  removedAsSaid,
  showsWholeNameLine,
  someGenericLine,
  tipExample,
} from "@/lib/descriptiveNotice";
import descriptiveFixture from "@/test/fixtures/search-v2-descriptive.json";
import textFixture from "@/test/fixtures/search-v2-text.json";

// 설명적 이름 안내(API 계약 v2 §2-7·§4-7). 시험 자료는 계약 픽스처에서 새 선택 필드를 뺀 것에 시험 안에서
// name_words·famous·뺀 낱말을 더해 만든다 — 픽스처의 구체 값(위험도·상표명)에 기대지 않는다. 픽스처
// 그대로의 화면은 맨 아래 묶음에서 따로 본다.
const BASE: SearchV2Response = (() => {
  const parsed = SearchV2ResponseSchema.parse(textFixture);
  delete parsed.famous;
  delete parsed.name_words;
  delete parsed.cross_goods_more;
  delete parsed.overall.famous_floor;
  for (const candidate of parsed.candidates) {
    delete candidate.famous_brand;
    delete candidate.cross_goods;
    candidate.salient = { ...candidate.salient, query_tokens: [], removed: [] };
  }
  return parsed;
})();

const TITLE = "이 이름은 상표로 등록받기 어려울 수 있어요";
const FOLLOW =
  "이런 말은 다른 가게도 자기 상품을 설명하려면 써야 해서, 한 사람만 쓰도록 등록받기 어려워요. 등록이 안 되면 다른 가게가 같은 이름을 써도 막을 수 없어요.";
const TIP_COIN = "직접 지은 말을 이름의 중심에 넣어 보세요.";
const TIP_KEEP = "설명하는 말은 같이 써도 괜찮아요. 다만 그 말 자체는 혼자 쓸 수 없어요.";
const FOOTNOTE =
  "최종 판단은 특허청 심사에서 정해져요. 오래 써서 많은 사람이 알아보는 이름은 예외가 될 수 있어요.";
const SOME_FOLLOW = "이런 말은 누구나 써야 해서 혼자 쓸 수 없어요.";
const WHOLE_NAME = "설명하는 말로만 된 이름이라, 아래는 이름 전체를 견준 결과예요.";
const COMMON = "흔히 쓰는 말";

type Side = "query" | "candidate" | "both";

function word(text: string, category: string | null): SearchV2NameWord {
  return { word: text, distinctive: category === null, category, reason: "시험" };
}

function nameWords(
  words: SearchV2NameWord[],
  extra: Partial<SearchV2NameWords> = {},
): SearchV2NameWords {
  const weak = words.filter((item) => !item.distinctive).length;
  const generic = weak === 0 ? "none" : weak === words.length ? "all" : "some";
  return { generic, words, more: 0, more_generic: 0, ...extra };
}

const COFFEE_SHOP = nameWords([
  word("맛있는", "성질·품질"),
  word("커피", "상품 이름"),
  word("전문점", "성질·품질"),
]);
const BLUE_COFFEE = nameWords([word("블루", null), word("커피", "상품 이름")]);

function famousMatch(overrides: Partial<SearchV2FamousMatch> = {}): SearchV2FamousMatch {
  return {
    brand: "김가네",
    level: "강함",
    basis: "이름",
    notation: "김가네",
    matched_text: "김가네",
    protection: "같은·가까운 업종 중심",
    goods_overlap: true,
    floor: "위험",
    logos: [],
    ...overrides,
  };
}

/** 약한 일치(이름)·로고로만 강한 일치 — 이 둘의 배너 아래에는 설명적 이름 안내가 그대로 온다. */
const WEAK_MATCH = famousMatch({ level: "약함", floor: "검토 권장" });
const LOGO_MATCH = famousMatch({ basis: "로고", notation: null, matched_text: null });

function resultWith(
  words: SearchV2NameWords | undefined,
  matches?: SearchV2FamousMatch[],
  status = "checked",
): SearchV2Response {
  const result = structuredClone(BASE);
  if (words) result.name_words = words;
  if (matches) result.famous = { status, brand_count: 58, matches };
  return result;
}

/** 후보마다 뺀 낱말을 정한다 — 한 벌이면 모든 후보에, 여러 벌이면 후보 순서대로(모자라면 빈 것). */
function withRemoved(
  result: SearchV2Response,
  ...perCandidate: Array<Array<[string, Side]>>
): SearchV2Response {
  result.candidates.forEach((candidate, index) => {
    const items = perCandidate.length === 1 ? perCandidate[0] : (perCandidate[index] ?? []);
    candidate.salient = {
      ...candidate.salient,
      removed: items.map(([token, side]) => ({ token, reason: "시험", side })),
    };
  });
  return result;
}

/** 일부 낱말만 식별력 없는 말인 응답 — 모든 후보에서 그 낱말들을 뺀 것으로. */
function someResult(words: SearchV2NameWords): SearchV2Response {
  const weak = words.words.filter((item) => !item.distinctive).map((item) => item.word);
  return withRemoved(
    resultWith(words),
    weak.map((token) => [token, "query"]),
  );
}

function renderResult(
  result: SearchV2Response,
  queryName: string | null = "맛있는 커피 전문점",
  onRename = vi.fn(),
) {
  render(
    <ResultViewV2
      result={result}
      queryPreview={null}
      queryHasName
      queryName={queryName}
      onReset={vi.fn()}
      onRename={onRename}
    />,
  );
  return onRename;
}

function notice() {
  return screen.getByTestId("descriptive-notice");
}

describe("설명적 이름 안내 — 큰 안내", () => {
  it("제목·본문·낱말 목록·이어지는 설명·해 볼 것·버튼·작은 글씨를 정해진 글자 그대로", () => {
    renderResult(resultWith(COFFEE_SHOP));
    const box = notice();
    expect(box).toHaveAttribute("data-kind", "big");
    expect(within(box).getByRole("heading", { level: 2, name: TITLE })).toBeInTheDocument();
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      "'맛있는 커피 전문점'은 모두 상품을 설명하거나 누구나 쓰는 말이에요.",
    );
    const items = within(within(box).getByTestId("descriptive-words")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "맛있는 — 맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
      "커피 — 파는 상품이나 서비스의 이름 그 자체예요",
      "전문점 — 맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
    ]);
    expect(within(box).getByText(FOLLOW)).toBeInTheDocument();
    expect(within(box).getByRole("heading", { level: 3, name: "이렇게 해 보세요" })).toBeInTheDocument();
    const tips = within(within(box).getByTestId("descriptive-tips")).getAllByRole("listitem");
    expect(tips.map((item) => item.textContent)).toEqual([
      `${TIP_COIN} 예: '○○ 커피'처럼요.`,
      TIP_KEEP,
    ]);
    expect(within(box).getByRole("button", { name: "다른 이름으로 다시 확인하기" })).toBeInTheDocument();
    expect(within(box).getByTestId("descriptive-footnote")).toHaveTextContent(FOOTNOTE);
    // 큰 안내는 처음부터 다 보인다 — 펼치는 버튼이 없다
    expect(within(box).queryByTestId("descriptive-toggle")).not.toBeInTheDocument();
  });

  it("상품 이름 낱말이 없으면 예시 문장을 붙이지 않는다", () => {
    renderResult(resultWith(nameWords([word("서울", "지역 이름"), word("김가네", "흔한 성·이름")])), "서울 김가네");
    expect(screen.queryByTestId("descriptive-example")).not.toBeInTheDocument();
    const tips = within(screen.getByTestId("descriptive-tips")).getAllByRole("listitem");
    expect(tips.map((item) => item.textContent)).toEqual([TIP_COIN, TIP_KEEP]);
  });

  it("상품 이름 낱말이 여럿이면 예시는 앞의 것으로", () => {
    renderResult(resultWith(nameWords([word("치킨", "상품 이름"), word("피자", "상품 이름")])), "치킨 피자");
    expect(screen.getByTestId("descriptive-example")).toHaveTextContent("예: '○○ 치킨'처럼요.");
  });

  it("버튼을 누르면 다시 확인하기 흐름을 부른다", () => {
    const onRename = renderResult(resultWith(COFFEE_SHOP));
    fireEvent.click(screen.getByRole("button", { name: "다른 이름으로 다시 확인하기" }));
    expect(onRename).toHaveBeenCalledTimes(1);
  });

  it("다시 확인하기 흐름이 없으면 버튼이 없다", () => {
    render(
      <ResultViewV2 result={resultWith(COFFEE_SHOP)} queryPreview={null} queryHasName onReset={vi.fn()} />,
    );
    expect(screen.getByTestId("descriptive-notice")).toHaveAttribute("data-kind", "big");
    expect(screen.queryByTestId("descriptive-retry")).not.toBeInTheDocument();
  });

  it("넣은 이름을 모르면 낱말을 띄어 이어 쓴다", () => {
    renderResult(resultWith(COFFEE_SHOP), null);
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'맛있는 커피 전문점'은 모두 상품을 설명하거나 누구나 쓰는 말이에요.",
    );
  });
});

describe("큰 안내의 조건 — '흔히 쓰는 말'이 아닌 분류의 낱말이 하나 이상 있을 때만", () => {
  it("큰 안내를 띄우는 분류는 다섯(흔히 쓰는 말·그 밖은 아니다)", () => {
    expect([...BIG_NOTICE_CATEGORIES].sort()).toEqual(
      ["상품 이름", "성질·품질", "지역 이름", "흔한 성·이름", "짧고 흔한 글자"].sort(),
    );
  });

  it.each(["상품 이름", "성질·품질", "지역 이름", "흔한 성·이름", "짧고 흔한 글자"])(
    "흔히 쓰는 말 사이에 %s 낱말이 하나라도 있으면 큰 안내",
    (category) => {
      const words = nameWords([word("daily", COMMON), word("낱말", category), word("garden", COMMON)]);
      renderResult(resultWith(words), "daily 낱말 garden");
      expect(notice()).toHaveAttribute("data-kind", "big");
      expect(screen.getByRole("heading", { level: 2, name: TITLE })).toBeInTheDocument();
    },
  );

  it("모든 낱말이 흔히 쓰는 말뿐이면 큰 안내 대신 작은 안내('자세히')", () => {
    const words = nameWords([word("fox", COMMON), word("books", COMMON)]);
    renderResult(resultWith(words), "Fox Books");
    const box = notice();
    expect(box).toHaveAttribute("data-kind", "all-small");
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      "'Fox Books'는 모두 누구나 쓰는 말이에요.",
    );
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    expect(screen.queryByTestId("descriptive-retry")).not.toBeInTheDocument();
    const toggle = within(box).getByRole("button", { name: "자세히" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const detail = within(box).getByTestId("descriptive-detail");
    expect(within(detail).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "fox — 여러 상표에 흔히 쓰이는 말이에요",
      "books — 여러 상표에 흔히 쓰이는 말이에요",
    ]);
    expect(within(detail).getByText(FOLLOW)).toBeInTheDocument();
  });

  it("'그 밖'과 모르는 분류는 큰 안내를 띄우지 않는다", () => {
    for (const category of ["그 밖", "앞으로 생길 분류"]) {
      const words = nameWords([word("fox", COMMON), word("낱말", category)]);
      expect(descriptiveNoticeKind(words, "none", [])).toBe("all-small");
    }
  });

  it("흔히 쓰는 말뿐이어도 전체 등급 옆 한 줄은 사실이면 그대로 보인다", () => {
    renderResult(resultWith(nameWords([word("fox", COMMON), word("books", COMMON)])), "Fox Books");
    expect(screen.getByTestId("descriptive-whole-name")).toHaveTextContent(WHOLE_NAME);
  });
});

describe("설명적 이름 안내 — 작은 안내(일부 낱말만)", () => {
  it("한 줄과 '왜요?' — 처음에는 접혀 있다", () => {
    renderResult(someResult(BLUE_COFFEE), "블루커피");
    const box = notice();
    expect(box).toHaveAttribute("data-kind", "some-small");
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      "'커피'는 누구나 쓰는 말이라 빼고 비교했어요.",
    );
    const toggle = within(box).getByRole("button", { name: "왜요?" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(box).getByTestId("descriptive-detail")).not.toBeVisible();
    // 큰 안내의 것은 없다
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    expect(screen.queryByTestId("descriptive-retry")).not.toBeInTheDocument();
  });

  it("펼치면 낱말별 분류 문구와 한 문장, 다시 누르면 접힌다", () => {
    renderResult(someResult(BLUE_COFFEE), "블루커피");
    const box = notice();
    const toggle = within(box).getByRole("button", { name: "왜요?" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = within(box).getByTestId("descriptive-detail");
    expect(detail).toBeVisible();
    expect(toggle).toHaveAttribute("aria-controls", detail.id);
    // 식별력 있는 낱말(블루)은 목록에 없다
    expect(within(detail).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "커피 — 파는 상품이나 서비스의 이름 그 자체예요",
    ]);
    expect(within(detail).getByText(SOME_FOLLOW)).toBeInTheDocument();
    expect(within(detail).queryByText(FOLLOW)).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(detail).not.toBeVisible();
  });

  it("빠진 낱말이 여럿이면 가운뎃점으로 잇는다", () => {
    const words = nameWords([word("서울", "지역 이름"), word("몬테로사", null), word("커피", "상품 이름")]);
    renderResult(someResult(words), "서울 몬테로사 커피");
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'서울·커피'는 누구나 쓰는 말이라 빼고 비교했어요.",
    );
  });
});

describe("작은 안내(일부 낱말만)의 조건 — '빼고 비교했어요'가 보이는 후보 모두에서 사실일 때만", () => {
  const COFFEE: [string, Side] = ["커피", "query"];

  it("모든 후보에서 그 낱말을 뺐으면 보인다(양쪽에서 함께 뺀 것도)", () => {
    renderResult(withRemoved(resultWith(BLUE_COFFEE), [["커피", "both"], ["cafe", "candidate"]]), "블루커피");
    expect(notice()).toHaveAttribute("data-kind", "some-small");
  });

  it("어느 후보 하나에서라도 빼지 않았으면 그리지 않는다", () => {
    // 둘째 후보는 결합 규칙 등으로 그 낱말을 빼지 않고 견준 쌍
    renderResult(withRemoved(resultWith(BLUE_COFFEE), [COFFEE], [], [COFFEE], [COFFEE]), "블루커피");
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
    expect(screen.getByTestId("overall-grade")).toBeInTheDocument();
  });

  it("후보 쪽에서만 약한 낱말로 뺀 것은 질의의 낱말을 뺀 것이 아니다", () => {
    renderResult(withRemoved(resultWith(BLUE_COFFEE), [["커피", "candidate"]]), "블루커피");
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
  });

  it("실린 낱말 가운데 하나라도 빠지지 않았으면 그리지 않는다", () => {
    const words = nameWords([word("서울", "지역 이름"), word("몬테로사", null), word("커피", "상품 이름")]);
    renderResult(withRemoved(resultWith(words), [COFFEE]), "서울 몬테로사 커피");
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
  });

  it("상표명이 없는 후보(로고만 견준 후보)는 보지 않는다", () => {
    const result = withRemoved(resultWith(BLUE_COFFEE), [COFFEE], [], [COFFEE], [COFFEE]);
    result.candidates[1].title = null;
    renderResult(result, "블루커피");
    expect(notice()).toHaveAttribute("data-kind", "some-small");
  });

  it("이름을 견준 후보가 하나도 없으면 그리지 않는다", () => {
    const result = resultWith(BLUE_COFFEE);
    for (const candidate of result.candidates) candidate.title = null;
    expect(removedAsSaid(BLUE_COFFEE, result.candidates)).toBe(false);
    expect(removedAsSaid(BLUE_COFFEE, [])).toBe(false);
    renderResult(result, "블루커피");
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
  });

  it("규칙 — 종류 정하기", () => {
    const removed = someResult(BLUE_COFFEE).candidates;
    const untouched = resultWith(BLUE_COFFEE).candidates;
    expect(descriptiveNoticeKind(BLUE_COFFEE, "none", removed)).toBe("some-small");
    expect(descriptiveNoticeKind(BLUE_COFFEE, "banner", removed)).toBe("some-small");
    expect(descriptiveNoticeKind(BLUE_COFFEE, "none", untouched)).toBeNull();
    // 모든 낱말이 식별력 없는 말이면 후보의 뺀 낱말과 무관하다
    expect(descriptiveNoticeKind(COFFEE_SHOP, "none", untouched)).toBe("big");
    expect(descriptiveNoticeKind(COFFEE_SHOP, "banner", untouched)).toBe("all-small");
    expect(descriptiveNoticeKind(undefined, "none", removed)).toBeNull();
    expect(descriptiveNoticeKind(nameWords([word("블루", null)]), "none", removed)).toBeNull();
    // 유명 상표 배너가 이름 쪽의 강한 일치로 떴으면 어떤 안내도 없다
    expect(descriptiveNoticeKind(BLUE_COFFEE, "name-strong", removed)).toBeNull();
    expect(descriptiveNoticeKind(COFFEE_SHOP, "name-strong", untouched)).toBeNull();
  });
});

describe("설명적 이름 안내 — 작은 안내(모든 낱말인데 유명 상표 배너가 있음 — 약한 일치·로고로만 강한 일치)", () => {
  const KIMGANE = nameWords([word("김가네", "흔한 성·이름")]);

  it.each([
    ["약함", WEAK_MATCH],
    ["강함 — 로고로만", LOGO_MATCH],
  ])("유명 상표 배너(%s)가 있으면 큰 안내 대신 한 줄과 '자세히'", (_level, match) => {
    renderResult(resultWith(KIMGANE, [match]), "김가네");
    const box = notice();
    expect(box).toHaveAttribute("data-kind", "all-small");
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      "'김가네'는 모두 누구나 쓰는 말이에요.",
    );
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    const toggle = within(box).getByRole("button", { name: "자세히" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const detail = within(box).getByTestId("descriptive-detail");
    expect(within(detail).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "김가네 — 흔한 성이나 흔히 쓰는 이름이에요",
    ]);
    // 펼치면 큰 안내의 낱말 목록과 이어지는 설명
    expect(within(detail).getByText(FOLLOW)).toBeInTheDocument();
  });
});

describe("유명 상표 배너가 이름 쪽의 강한 일치로 뜨면 설명적 이름 안내를 그리지 않는다", () => {
  const PARIS = nameWords([word("파리", "지역 이름"), word("바게트", "상품 이름")]);
  const PARIS_MATCH = famousMatch({ brand: "파리바게뜨", notation: "파리바게뜨", matched_text: "파리바게트" });
  const OCR_MATCH = famousMatch({ basis: "이미지 속 글자" });

  function expectBannerOnly() {
    expect(screen.getByTestId("famous-banner")).toHaveAttribute("data-level", "강함");
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
    expect(screen.queryByTestId("descriptive-whole-name")).not.toBeInTheDocument();
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  }

  it("이름 강함 + 모든 낱말이 식별력 없는 말(파리바게트): 배너만 — 큰 안내도 작은 안내도 전체 등급 옆 한 줄도 없다", () => {
    renderResult(resultWith(PARIS, [PARIS_MATCH]), "파리바게트");
    expectBannerOnly();
    expect(screen.getByRole("heading", { level: 2, name: /파리바게뜨/ })).toBeInTheDocument();
    // 결과가 뜰 때 포커스를 받는 제목은 결과 화면의 제목(h1) 하나뿐이다 — 배너의 제목은 그 아래 h2
    const headings = document.querySelectorAll("[data-phase-heading]");
    expect(headings).toHaveLength(1);
    expect(headings[0]).toBe(screen.getByRole("heading", { level: 1, name: "검색 결과" }));
  });

  it("이름 강함 + 한 낱말(김가네)도 같다", () => {
    renderResult(resultWith(nameWords([word("김가네", "흔한 성·이름")]), [famousMatch()]), "김가네");
    expectBannerOnly();
  });

  it("이름 강함 + 흔히 쓰는 말뿐인 이름", () => {
    const words = nameWords([word("fox", COMMON), word("books", COMMON)]);
    renderResult(resultWith(words, [famousMatch()]), "Fox Books");
    expectBannerOnly();
  });

  it("이름 강함 + 일부 낱말만(그 낱말을 실제로 빼고 견줬어도) 작은 안내가 없다", () => {
    const result = someResult(BLUE_COFFEE);
    result.famous = { status: "checked", brand_count: 58, matches: [famousMatch()] };
    renderResult(result, "블루커피");
    expectBannerOnly();
  });

  it("이미지 속 글자 강함도 같다", () => {
    renderResult(resultWith(PARIS, [OCR_MATCH]), "파리바게트");
    expectBannerOnly();
  });

  it("첫째 일치가 로고여도 둘째 줄의 일치가 이름 강함이면 그리지 않는다", () => {
    const second = famousMatch({ brand: "뚜레쥬르", notation: "뚜레쥬르", matched_text: "뚜레쥬르" });
    renderResult(resultWith(PARIS, [LOGO_MATCH, second]), "파리바게트");
    expect(screen.getByTestId("famous-second")).toBeInTheDocument();
    expectBannerOnly();
  });

  it("지금대로: 약한 일치·로고로만 강한 일치는 일부 낱말만일 때도 작은 안내를 그대로 보인다", () => {
    for (const match of [WEAK_MATCH, LOGO_MATCH]) {
      const result = someResult(BLUE_COFFEE);
      result.famous = { status: "checked", brand_count: 58, matches: [match] };
      const view = render(
        <ResultViewV2 result={result} queryPreview={null} queryHasName queryName="블루커피" onReset={vi.fn()} />,
      );
      expect(notice()).toHaveAttribute("data-kind", "some-small");
      view.unmount();
    }
  });

  it("규칙 — 배너가 설명적 이름 안내에 주는 영향", () => {
    const state = (matches: SearchV2FamousMatch[], status = "checked") =>
      famousBannerState({ status, brand_count: 58, matches });
    expect(famousBannerState(undefined)).toBe("none");
    expect(state([])).toBe("none");
    expect(state([famousMatch()], "unavailable")).toBe("none");
    expect(state([famousMatch({ level: "설명적 사용", floor: null })])).toBe("none");
    expect(state([famousMatch({ level: "앞으로 생길 종류" })])).toBe("none"); // 배너를 그리지 않는다
    expect(state([WEAK_MATCH])).toBe("banner");
    expect(state([LOGO_MATCH])).toBe("banner");
    expect(state([LOGO_MATCH, WEAK_MATCH])).toBe("banner");
    expect(state([famousMatch()])).toBe("name-strong");
    expect(state([OCR_MATCH])).toBe("name-strong");
    expect(state([famousMatch(), WEAK_MATCH])).toBe("name-strong");
    expect(state([LOGO_MATCH, famousMatch({ brand: "뚜레쥬르" })])).toBe("name-strong");
  });
});

describe("맨 위 안내의 순서 — ① 유명 상표 배너(강함·약함) ② 설명적 이름 안내 ③ 유명 상표의 설명적 사용", () => {
  function follows(first: HTMLElement, second: HTMLElement): boolean {
    return Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);
  }

  it.each([
    ["약함", WEAK_MATCH],
    ["강함 — 로고로만", LOGO_MATCH],
  ])("유명 상표 배너(%s)가 먼저, 설명적 이름 안내가 그 다음, 전체 등급이 그 아래", (_level, match) => {
    renderResult(resultWith(nameWords([word("김가네", "흔한 성·이름")]), [match]), "김가네");
    const banner = screen.getByTestId("famous-banner");
    expect(follows(banner, notice())).toBe(true);
    expect(follows(notice(), screen.getByTestId("overall-grade"))).toBe(true);
  });

  it("유명 상표의 설명적 사용 안내는 설명적 이름 안내(큰 안내) 뒤에 온다", () => {
    const bbq = famousMatch({ brand: "BBQ", level: "설명적 사용", notation: "BBQ", matched_text: "BBQ", floor: null });
    renderResult(resultWith(nameWords([word("텍사스", "지역 이름"), word("bbq", "성질·품질")]), [bbq]), "텍사스 BBQ");
    const box = notice();
    const banner = screen.getByTestId("famous-banner");
    expect(box).toHaveAttribute("data-kind", "big"); // 설명적 사용 배너는 강함·약함이 아니다
    expect(banner).toHaveAttribute("data-level", "설명적 사용");
    expect(follows(box, banner)).toBe(true);
    expect(follows(banner, screen.getByTestId("overall-grade"))).toBe(true);
    // 결과가 뜰 때 포커스를 받는 제목은 결과 화면의 제목(h1) 하나뿐이고, 안내의 제목들은 그 아래 h2
    const headings = document.querySelectorAll("[data-phase-heading]");
    expect(headings).toHaveLength(1);
    expect(headings[0]).toHaveTextContent("검색 결과");
    expect(screen.getByRole("heading", { level: 2, name: TITLE })).toBeInTheDocument();
  });

  it("유명 상표 확인을 하지 못했을 때의 한 줄은 맨 위에 그대로, 큰 안내는 그 아래", () => {
    renderResult(resultWith(COFFEE_SHOP, [], "unavailable"));
    const line = screen.getByTestId("famous-unavailable");
    expect(notice()).toHaveAttribute("data-kind", "big");
    expect(follows(line, notice())).toBe(true);
  });

  it("유명 상표 일치가 없으면(확인함) 큰 안내", () => {
    renderResult(resultWith(COFFEE_SHOP, []));
    expect(notice()).toHaveAttribute("data-kind", "big");
    expect(screen.queryByTestId("famous-banner")).not.toBeInTheDocument();
  });
});

describe("설명적 이름 안내 — 조사는 받침에 맞춘다", () => {
  it.each([
    ["맛있는 커피 전문점", "은"],
    ["커피", "는"],
    ["서울 식당", "은"],
    ["Best Coffee", "는"], // 한글이 아니면 받침 없는 것으로
    ["치킨 24", "는"],
  ])("이름 %s", (name, josa) => {
    expect(bigLine(name)).toBe(`'${name}'${josa} 모두 상품을 설명하거나 누구나 쓰는 말이에요.`);
    expect(allSmallLine(name)).toBe(`'${name}'${josa} 모두 누구나 쓰는 말이에요.`);
  });

  it.each([
    [["커피"], "'커피'는 누구나 쓰는 말이라 빼고 비교했어요."],
    [["전문점"], "'전문점'은 누구나 쓰는 말이라 빼고 비교했어요."],
    [["커피", "서울"], "'커피·서울'은 누구나 쓰는 말이라 빼고 비교했어요."], // 마지막 낱말의 받침
    [["서울", "coffee"], "'서울·coffee'는 누구나 쓰는 말이라 빼고 비교했어요."],
  ])("빠진 낱말 %j", (words, line) => {
    expect(someGenericLine(words, 0)).toBe(line);
  });

  it("화면에도 같은 조사로 나온다", () => {
    renderResult(someResult(nameWords([word("블루", null), word("전문점", "성질·품질")])), "블루 전문점");
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'전문점'은 누구나 쓰는 말이라 빼고 비교했어요.",
    );
  });
});

describe("설명적 이름 안내 — 낱말이 여섯 개를 넘을 때", () => {
  const SIX = ["가", "나", "다", "라", "마", "바"].map((text) => word(text, "짧고 흔한 글자"));

  it("큰 안내: 실린 여섯 낱말 뒤에 '외 N개'", () => {
    renderResult(resultWith(nameWords(SIX, { generic: "all", more: 2, more_generic: 2 })), "가 나 다 라 마 바 사 아");
    const items = within(screen.getByTestId("descriptive-words")).getAllByRole("listitem");
    expect(items).toHaveLength(7);
    expect(items[0]).toHaveTextContent("가 — 너무 짧거나 흔한 글자·숫자예요");
    expect(screen.getByTestId("descriptive-more")).toHaveTextContent("외 2개");
    // 본문은 넣은 이름 전체
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'가 나 다 라 마 바 사 아'는 모두 상품을 설명하거나 누구나 쓰는 말이에요.",
    );
  });

  it("작은 안내: 실린 낱말과 '외 N개는' — 싣지 않은 낱말까지 빠졌을 때만", () => {
    const words = nameWords([word("몬테로사", null), ...SIX.slice(0, 5)], {
      generic: "some",
      more: 3,
      more_generic: 2,
    });
    const listed: Array<[string, Side]> = SIX.slice(0, 5).map((item) => [item.word, "query"]);
    const all: Array<[string, Side]> = [...listed, ["사", "query"], ["아", "both"]];
    renderResult(withRemoved(resultWith(words), all), "몬테로사 가 나 다 라 마 바 사 아");
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'가·나·다·라·마' 외 2개는 누구나 쓰는 말이라 빼고 비교했어요.",
    );
    fireEvent.click(screen.getByRole("button", { name: "왜요?" }));
    expect(screen.getByTestId("descriptive-more")).toHaveTextContent("외 2개");
    // 실린 다섯 낱말만 빠졌으면(싣지 않은 둘은 모름) 사실인지 알 수 없어 그리지 않는다
    expect(removedAsSaid(words, withRemoved(resultWith(words), listed).candidates)).toBe(false);
    expect(removedAsSaid(words, withRemoved(resultWith(words), all).candidates)).toBe(true);
  });

  it("실리지 않은 낱말에 식별력 없는 말이 없으면 '외 N개'를 붙이지 않는다", () => {
    const words = nameWords([...SIX.slice(0, 2), word("몬테로사", null)], {
      generic: "some",
      more: 4,
      more_generic: 0,
    });
    renderResult(withRemoved(resultWith(words), [["가", "query"], ["나", "query"]]), "가 나 몬테로사 …");
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'가·나'는 누구나 쓰는 말이라 빼고 비교했어요.",
    );
    expect(screen.queryByTestId("descriptive-more")).not.toBeInTheDocument();
  });

  it("식별력 없는 낱말이 실리지 않은 쪽에만 있으면 수로만 말한다", () => {
    expect(someGenericLine([], 2)).toBe("이름의 낱말 2개는 누구나 쓰는 말이라 빼고 비교했어요.");
  });
});

describe("설명적 이름 안내 — 분류 문구", () => {
  it("여섯 분류와 그 밖의 문구(글자 그대로)", () => {
    expect(CATEGORY_TEXT).toEqual({
      "상품 이름": "파는 상품이나 서비스의 이름 그 자체예요",
      "성질·품질": "맛·품질·재료·쓰임새 같은 성질을 설명하는 말이에요",
      "흔히 쓰는 말": "여러 상표에 흔히 쓰이는 말이에요",
      "지역 이름": "널리 알려진 지역 이름이에요",
      "흔한 성·이름": "흔한 성이나 흔히 쓰는 이름이에요",
      "짧고 흔한 글자": "너무 짧거나 흔한 글자·숫자예요",
    });
    expect(CATEGORY_OTHER_TEXT).toBe("식별력이 약한 말이에요");
    expect(categoryText("그 밖")).toBe("식별력이 약한 말이에요");
    expect(categoryText("앞으로 생길 분류")).toBe("식별력이 약한 말이에요");
    expect(categoryText(null)).toBe("식별력이 약한 말이에요");
    expect(tipExample("커피")).toBe("예: '○○ 커피'처럼요.");
    expect(NOTICE_TEXT.bigTitle).toBe(TITLE);
    expect(NOTICE_TEXT.wholeName).toBe(WHOLE_NAME);
  });

  it("분류마다 그 문구로 그린다", () => {
    const words = Object.keys(CATEGORY_TEXT).map((category, index) => word(`낱말${index}`, category));
    renderResult(resultWith(nameWords(words)), "여섯 낱말");
    const items = within(screen.getByTestId("descriptive-words")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(
      Object.values(CATEGORY_TEXT).map((text, index) => `낱말${index} — ${text}`),
    );
  });
});

describe("설명적 이름 안내 — 그리지 않는 경우", () => {
  it.each([
    ["필드가 없음(이름 없는 질의·옛 서버)", undefined],
    ["식별력 없는 낱말이 없음", nameWords([word("스타벅스", null)])],
    ["낱말이 없음", nameWords([])],
    ["모르는 generic 값", nameWords([word("커피", "상품 이름")], { generic: "most" })],
  ])("%s", (_label, words) => {
    renderResult(resultWith(words));
    expect(screen.queryByTestId("descriptive-notice")).not.toBeInTheDocument();
    expect(screen.queryByTestId("descriptive-whole-name")).not.toBeInTheDocument();
    expect(screen.getByTestId("overall-grade")).toBeInTheDocument();
  });
});

describe("전체 등급 옆의 한 줄 — 이름 전체를 견준 결과", () => {
  function allWithRemoved(side: Side): SearchV2Response {
    return withRemoved(resultWith(COFFEE_SHOP), [], [["맛있는", side]]);
  }

  it("모든 낱말이 설명하는 말이고 보이는 후보에서 질의의 낱말이 빠지지 않았으면 보인다", () => {
    renderResult(resultWith(COFFEE_SHOP));
    expect(screen.getByTestId("descriptive-whole-name")).toHaveTextContent(WHOLE_NAME);
  });

  it("후보 쪽 낱말만 빠진 것은 그대로 보인다", () => {
    renderResult(allWithRemoved("candidate"));
    expect(screen.getByTestId("descriptive-whole-name")).toBeInTheDocument();
  });

  it.each(["both", "query"] as const)(
    "어느 후보와 견줄 때 질의의 낱말이 빠졌으면(%s) 사실이 아니어서 그리지 않는다",
    (side) => {
      renderResult(allWithRemoved(side));
      expect(screen.queryByTestId("descriptive-whole-name")).not.toBeInTheDocument();
      expect(notice()).toHaveAttribute("data-kind", "big"); // 안내는 그대로
    },
  );

  it("일부 낱말만 설명하는 말이면 없다", () => {
    renderResult(someResult(BLUE_COFFEE), "블루커피");
    expect(screen.queryByTestId("descriptive-whole-name")).not.toBeInTheDocument();
  });

  it.each([
    ["약함", WEAK_MATCH],
    ["강함 — 로고로만", LOGO_MATCH],
  ])("유명 상표 배너(%s)가 있어 작은 안내일 때도 사실이면 보인다", (_level, match) => {
    renderResult(resultWith(nameWords([word("김가네", "흔한 성·이름")]), [match]), "김가네");
    expect(screen.getByTestId("descriptive-whole-name")).toHaveTextContent(WHOLE_NAME);
  });

  it("규칙", () => {
    const candidates = resultWith(COFFEE_SHOP).candidates;
    expect(showsWholeNameLine(COFFEE_SHOP, candidates, "none")).toBe(true);
    expect(showsWholeNameLine(COFFEE_SHOP, candidates, "banner")).toBe(true);
    expect(showsWholeNameLine(COFFEE_SHOP, [], "none")).toBe(true);
    expect(showsWholeNameLine(undefined, candidates, "none")).toBe(false);
    expect(showsWholeNameLine(nameWords([word("블루", null)]), candidates, "none")).toBe(false);
    // 유명 상표 배너가 이름 쪽의 강한 일치로 떴으면 이 줄도 그리지 않는다
    expect(showsWholeNameLine(COFFEE_SHOP, candidates, "name-strong")).toBe(false);
  });
});

describe("설명적 이름 안내 — 접근성", () => {
  it("큰 안내: 제목으로 이름 붙은 영역, 종류는 글자로도, 아이콘은 숨김", () => {
    renderResult(resultWith(COFFEE_SHOP));
    const region = screen.getByRole("region", { name: TITLE });
    expect(region).toBe(notice());
    expect(within(region).getByTestId("descriptive-label")).toHaveTextContent(
      "이름 안내 · 설명하는 말로만 된 이름",
    );
    for (const icon of region.querySelectorAll("svg")) {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    }
    // 포커스는 결과 화면의 제목(h1)이 받는다 — 안내의 제목(h2)은 포커스를 가져가지 않는다
    const heading = within(region).getByRole("heading", { level: 2 });
    expect(heading).not.toHaveAttribute("data-phase-heading");
    expect(heading).not.toHaveAttribute("tabindex");
  });

  it("작은 안내: 보이지 않는 제목으로 이름 붙은 영역, 펼침 상태를 알리는 버튼", () => {
    renderResult(someResult(BLUE_COFFEE), "블루커피");
    const region = screen.getByRole("region", { name: "이름에 든 누구나 쓰는 말" });
    expect(region).toBe(notice());
    const toggle = within(region).getByRole("button", { name: "왜요?" });
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // 작은 안내의 제목은 포커스를 가져가지 않는다
    expect(within(region).getByRole("heading", { level: 2 })).not.toHaveAttribute("data-phase-heading");
  });

  it("질의에서 온 글자는 글로만 그린다(HTML 로 해석하지 않는다)", () => {
    const html = '<img src=x onerror="alert(1)">';
    renderResult(resultWith(nameWords([word(html, "상품 이름")])), html);
    const box = notice();
    expect(box.querySelector("img")).toBeNull();
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      `'${html}'는 모두 상품을 설명하거나 누구나 쓰는 말이에요.`,
    );
    expect(within(box).getByTestId("descriptive-words")).toHaveTextContent(html);
  });
});

describe("계약 픽스처 그대로의 화면", () => {
  it("§3-4 설명적 이름(맛있는 커피 전문점 + 카페): 큰 안내, 예시는 커피", () => {
    renderResult(SearchV2ResponseSchema.parse(descriptiveFixture), "맛있는 커피 전문점");
    const box = notice();
    expect(box).toHaveAttribute("data-kind", "big");
    expect(within(box).getByTestId("descriptive-line")).toHaveTextContent(
      "'맛있는 커피 전문점'은 모두 상품을 설명하거나 누구나 쓰는 말이에요.",
    );
    const items = within(within(box).getByTestId("descriptive-words")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent?.split(" — ")[0])).toEqual(["맛있는", "커피", "전문점"]);
    expect(within(box).getByTestId("descriptive-example")).toHaveTextContent("예: '○○ 커피'처럼요.");
    // 이 응답의 후보 하나는 질의의 낱말(맛있는)이 함께 빠진 쌍이라 "이름 전체" 한 줄은 없다
    expect(
      descriptiveFixture.candidates.some((candidate) =>
        candidate.salient.removed.some((item) => item.side !== "candidate"),
      ),
    ).toBe(true);
    expect(screen.queryByTestId("descriptive-whole-name")).not.toBeInTheDocument();
  });

  it("§3-1 문자상표(블루커피 + 카페): 모든 후보에서 '커피'를 빼고 견줘 작은 안내가 보인다", () => {
    const parsed = SearchV2ResponseSchema.parse(textFixture);
    expect(removedAsSaid(parsed.name_words!, parsed.candidates)).toBe(true);
    renderResult(parsed, "블루커피");
    expect(notice()).toHaveAttribute("data-kind", "some-small");
    expect(screen.getByTestId("descriptive-line")).toHaveTextContent(
      "'커피'는 누구나 쓰는 말이라 빼고 비교했어요.",
    );
  });
});
