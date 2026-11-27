import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResultViewV2 from "@/components/ResultViewV2";
import {
  SearchV2ResponseSchema,
  type SearchV2Candidate,
  type SearchV2CrossGoods,
  type SearchV2Response,
} from "@/lib/contracts";
import {
  CROSS_GOODS_MORE_LIMIT,
  CROSS_GOODS_TEXT,
  crossGoodsLine,
  crossGoodsMore,
  crossGoodsMoreNote,
  crossGoodsMoreTitle,
  isCrossGoods,
  showsCrossGoodsOverallLine,
} from "@/lib/crossGoods";
import famousFixture from "@/test/fixtures/search-v2-famous.json";
import imageFixture from "@/test/fixtures/search-v2-image.json";
import textFixture from "@/test/fixtures/search-v2-text.json";

// 업종은 다르지만 표장이 닮은 후보(API 계약 v2 §2-8·§4-8). 시험 자료는 계약 픽스처에서 선택 필드를 뺀
// 것에 시험 안에서 cross_goods·cross_goods_more·famous 를 더해 만든다 — 픽스처의 구체 값에 기대지
// 않는다. 픽스처 그대로의 화면은 맨 아래 묶음에서 따로 본다.
const BASE: SearchV2Response = (() => {
  const parsed = SearchV2ResponseSchema.parse(textFixture);
  delete parsed.famous;
  delete parsed.name_words;
  delete parsed.cross_goods_more;
  delete parsed.overall.famous_floor;
  for (const candidate of parsed.candidates) {
    delete candidate.famous_brand;
    delete candidate.cross_goods;
  }
  return parsed;
})();

const BADGE = "업종 다름";
const PLAIN =
  "표장은 닮았지만 업종이 달라요. 보통은 함께 등록될 수 있어요. 다만 나중에 이 업종으로 넓히면 문제가 될 수 있어요.";
const FAMOUS = "업종은 다르지만 널리 알려진 상표라 문제가 될 수 있어요.";
const OVERALL = "가장 닮은 상표가 다른 업종에 있어요. 업종이 다르면 함께 등록될 수도 있어요.";

const FLAGGED: SearchV2CrossGoods = {
  differs: true,
  grade_without_goods: "검토 권장",
  flagged: true,
};
const DIFFERENT_ONLY: SearchV2CrossGoods = {
  differs: true,
  grade_without_goods: "주의",
  flagged: false,
};
const SAME: SearchV2CrossGoods = { differs: false, grade_without_goods: null, flagged: false };
const UNKNOWN: SearchV2CrossGoods = { differs: null, grade_without_goods: null, flagged: false };

/** 앞의 후보마다 cross_goods 를 정한다(undefined 면 필드 없음). */
function resultWith(...fields: Array<SearchV2CrossGoods | undefined>): SearchV2Response {
  const result = structuredClone(BASE);
  result.candidates.forEach((candidate, index) => {
    const field = fields[index];
    if (field) candidate.cross_goods = { ...field };
  });
  return result;
}

/** 처음 보이는 범위 밖의 후보 — 출원번호를 달리해 만든다. */
function outside(count: number, field: SearchV2CrossGoods = FLAGGED): SearchV2Candidate[] {
  return Array.from({ length: count }, (_, index) => ({
    ...structuredClone(BASE.candidates[0]),
    id: `40202600${String(index + 1).padStart(5, "0")}`,
    title: `범위 밖 상표 ${index + 1}`,
    cross_goods: { ...field },
  }));
}

function withMore(
  result: SearchV2Response,
  candidates: SearchV2Candidate[],
  count = candidates.length,
): SearchV2Response {
  result.cross_goods_more = { count, candidates };
  return result;
}

function renderResult(result: SearchV2Response) {
  return render(
    <ResultViewV2
      result={result}
      queryPreview={null}
      queryHasName
      queryName="블루커피"
      onReset={vi.fn()}
    />,
  );
}

/** 목록 바로 아래의 후보 카드(카드 안의 축·근거 목록은 세지 않는다). */
function cardsIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelector(":scope > ul")!.children) as HTMLElement[];
}

function cards() {
  return cardsIn(screen.getByRole("region", { name: "유사 상표 후보" }));
}

function moreCards() {
  return cardsIn(screen.getByTestId("cross-goods-more-panel"));
}

describe("후보 카드 — '업종 다름' 표시와 설명 한 줄", () => {
  it("정의에 맞는 후보에만 표시와 설명 한 줄이 붙는다", () => {
    renderResult(resultWith(FLAGGED, DIFFERENT_ONLY, SAME, UNKNOWN));
    const [first, second, third, fourth] = cards();
    expect(within(first).getByTestId("candidate-cross-goods")).toHaveTextContent(BADGE);
    expect(within(first).getByTestId("candidate-cross-goods-line")).toHaveTextContent(PLAIN);
    // 업종은 다르지만 업종 없이 본 등급이 낮은 후보·업종이 겹치는 후보·겹침을 모르는 후보
    for (const card of [second, third, fourth]) {
      expect(within(card).queryByTestId("candidate-cross-goods")).not.toBeInTheDocument();
      expect(within(card).queryByTestId("candidate-cross-goods-line")).not.toBeInTheDocument();
    }
    expect(screen.getAllByText(BADGE)).toHaveLength(1);
  });

  it("유명 상표 표시가 붙은 후보는 다른 문구", () => {
    const result = resultWith(FLAGGED, FLAGGED);
    result.candidates[1].famous_brand = "스타벅스";
    renderResult(result);
    const [first, second] = cards();
    expect(within(first).getByTestId("candidate-cross-goods-line")).toHaveTextContent(PLAIN);
    expect(within(second).getByTestId("candidate-famous-brand")).toHaveTextContent(
      "유명 상표 · 스타벅스",
    );
    expect(within(second).getByTestId("candidate-cross-goods")).toHaveTextContent(BADGE);
    const line = within(second).getByTestId("candidate-cross-goods-line");
    expect(line).toHaveTextContent(FAMOUS);
    expect(line).not.toHaveTextContent("보통은 함께 등록될 수 있어요");
  });

  it("필드가 없으면(업종을 넣지 않은 질의·옛 서버) 아무것도 그리지 않는다", () => {
    renderResult(resultWith());
    expect(screen.queryByTestId("candidate-cross-goods")).not.toBeInTheDocument();
    expect(screen.queryByTestId("candidate-cross-goods-line")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cross-goods-more")).not.toBeInTheDocument();
  });

  it("표시는 글자로 보인다(색만으로 구분하지 않는다) — 카드를 펼치지 않아도", () => {
    renderResult(resultWith(FLAGGED));
    const [first] = cards();
    const toggle = within(first).getAllByRole("button")[0];
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(within(toggle).getByText(BADGE)).toBeVisible();
    expect(within(toggle).getByText(PLAIN)).toBeVisible();
  });

  it("규칙", () => {
    const [first, second, third, fourth] = resultWith(
      FLAGGED,
      DIFFERENT_ONLY,
      SAME,
      UNKNOWN,
    ).candidates;
    expect([first, second, third, fourth].map(isCrossGoods)).toEqual([true, false, false, false]);
    expect(isCrossGoods(BASE.candidates[0])).toBe(false);
    expect(crossGoodsLine(first)).toBe(PLAIN);
    expect(crossGoodsLine({ ...first, famous_brand: "스타벅스" })).toBe(FAMOUS);
    expect(crossGoodsLine(second)).toBeNull();
    expect(crossGoodsLine({ ...third, famous_brand: "스타벅스" })).toBeNull();
    expect(CROSS_GOODS_TEXT).toMatchObject({ badge: BADGE, plain: PLAIN, famous: FAMOUS, overall: OVERALL });
  });
});

describe("전체 등급 옆 한 줄", () => {
  it("가장 위 후보가 정의에 맞는 후보면 보인다", () => {
    renderResult(resultWith(FLAGGED, SAME));
    expect(screen.getByTestId("cross-goods-overall")).toHaveTextContent(OVERALL);
  });

  it("가장 위 후보가 아니면 보이지 않는다", () => {
    renderResult(resultWith(SAME, FLAGGED, FLAGGED));
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("candidate-cross-goods")).toHaveLength(2);
  });

  it("유명 상표 바닥이 전체 등급을 정했으면 보이지 않는다", () => {
    const result = resultWith(FLAGGED);
    result.overall = { ...result.overall, grade: "위험", famous_floor: true };
    result.famous = {
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
          logos: [],
        },
      ],
    };
    renderResult(result);
    expect(screen.getByTestId("famous-floor-reason")).toBeInTheDocument();
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
    // 카드의 표시는 그대로
    expect(screen.getByTestId("candidate-cross-goods")).toBeInTheDocument();
    // 바닥이 정한 것이 아니면(famous_floor false) 유명 상표 확인이 있어도 보인다
    const shown = structuredClone(result);
    shown.overall = { ...shown.overall, famous_floor: false };
    expect(showsCrossGoodsOverallLine(shown)).toBe(true);
  });

  it("후보가 없으면 보이지 않는다", () => {
    const result = resultWith();
    result.candidates = [];
    result.overall = { ...result.overall, grade: null, prob: null, pattern: null };
    expect(showsCrossGoodsOverallLine(result)).toBe(false);
    renderResult(result);
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
  });

  it("맨 위 영역의 순서 — 유명 상표 배너 → 설명적 이름 안내 → 이 한 줄", () => {
    const result = resultWith(FLAGGED);
    result.famous = {
      status: "checked",
      brand_count: 58,
      matches: [
        {
          brand: "스타벅스",
          level: "약함",
          basis: "이름",
          notation: "스타벅스",
          matched_text: "스타벅수",
          protection: "업종 불문",
          goods_overlap: true,
          floor: "검토 권장",
          logos: [],
        },
      ],
    };
    result.overall = { ...result.overall, famous_floor: false };
    result.name_words = {
      generic: "all",
      words: [{ word: "커피", distinctive: false, category: "상품 이름", reason: "시험" }],
      more: 0,
      more_generic: 0,
    };
    renderResult(result);
    const banner = screen.getByTestId("famous-banner");
    const notice = screen.getByTestId("descriptive-notice");
    const line = screen.getByTestId("cross-goods-overall");
    const follows = (a: HTMLElement, b: HTMLElement) =>
      Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(follows(banner, notice)).toBe(true);
    expect(follows(notice, line)).toBe(true);
    // 기존 두 안내의 문구는 그대로
    expect(banner).toHaveTextContent("널리 알려진 상표 '스타벅스'와 이름이 닮았어요");
    expect(notice).toHaveTextContent("'블루커피'는 모두 누구나 쓰는 말이에요.");
  });
});

describe("목록 아래 접힌 칸 — 처음 보이는 범위 밖의 후보", () => {
  it("범위 밖에 정의에 맞는 후보가 없으면 칸을 만들지 않는다", () => {
    for (const result of [
      resultWith(FLAGGED), // 필드 없음(옛 서버)
      withMore(resultWith(FLAGGED), []), // 범위 안에 다 보인다
      withMore(resultWith(FLAGGED), [], 3), // 수만 있고 보일 후보가 없다
      withMore(resultWith(FLAGGED), outside(2, DIFFERENT_ONLY)), // 정의에 맞지 않는 후보뿐
    ]) {
      expect(crossGoodsMore(result)).toBeNull();
      const view = renderResult(result);
      expect(screen.queryByTestId("cross-goods-more")).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("제목에 수를 적고 처음에는 접혀 있다 — 펼치면 후보 카드가 보인다", () => {
    renderResult(withMore(resultWith(SAME), outside(2)));
    const section = screen.getByTestId("cross-goods-more");
    const toggle = within(section).getByRole("button", {
      name: "업종은 다르지만 표장이 닮은 상표 2건",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const panel = within(section).getByTestId("cross-goods-more-panel");
    expect(panel).not.toBeVisible();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    const items = moreCards();
    expect(items).toHaveLength(2);
    // 카드의 이름은 제목(h3 — 화면에는 보이지 않는다)과 카드 안의 글자로 두 번 읽힌다
    expect(within(items[0]).getByRole("heading", { level: 3, name: "범위 밖 상표 1" })).toBeInTheDocument();
    expect(within(items[0]).getAllByText("범위 밖 상표 1")).toHaveLength(2);
    for (const item of items) {
      expect(within(item).getByTestId("candidate-cross-goods")).toHaveTextContent(BADGE);
      expect(within(item).getByTestId("candidate-cross-goods-line")).toHaveTextContent(PLAIN);
    }
    expect(within(section).queryByTestId("cross-goods-more-note")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(panel).not.toBeVisible();
  });

  it("수가 다섯을 넘으면 다섯 개만 보이고 한 줄로 알린다", () => {
    renderResult(withMore(resultWith(SAME), outside(5), 12));
    const section = screen.getByTestId("cross-goods-more");
    fireEvent.click(
      within(section).getByRole("button", { name: "업종은 다르지만 표장이 닮은 상표 12건" }),
    );
    expect(moreCards()).toHaveLength(5);
    expect(within(section).getByTestId("cross-goods-more-note")).toHaveTextContent(
      "12건 가운데 표장이 가장 닮은 5건을 보여요.",
    );
  });

  it("응답에 다섯보다 많이 실려 와도 다섯 개까지만, 정의에 맞지 않는 후보는 뺀다", () => {
    const many = withMore(resultWith(SAME), outside(7));
    expect(crossGoodsMore(many)?.candidates).toHaveLength(CROSS_GOODS_MORE_LIMIT);
    const mixed = [...outside(1, DIFFERENT_ONLY), ...outside(3).slice(1)];
    const picked = crossGoodsMore(withMore(resultWith(SAME), mixed, 2));
    expect(picked?.candidates.map((candidate) => candidate.title)).toEqual([
      "범위 밖 상표 2",
      "범위 밖 상표 3",
    ]);
    expect(picked?.count).toBe(2);
  });

  it("유명 상표 표시가 붙은 후보는 칸 안에서도 다른 문구", () => {
    const [famous, plain] = outside(2);
    famous.famous_brand = "스타벅스";
    renderResult(withMore(resultWith(SAME), [famous, plain]));
    fireEvent.click(screen.getByTestId("cross-goods-more-toggle"));
    const items = moreCards();
    expect(within(items[0]).getByTestId("candidate-cross-goods-line")).toHaveTextContent(FAMOUS);
    expect(within(items[1]).getByTestId("candidate-cross-goods-line")).toHaveTextContent(PLAIN);
  });

  it("칸은 후보 목록 아래에 있고, 안의 카드도 펼쳐 볼 수 있다", () => {
    renderResult(withMore(resultWith(FLAGGED), outside(1)));
    const list = screen.getByRole("region", { name: "유사 상표 후보" });
    const section = screen.getByTestId("cross-goods-more");
    expect(list.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    fireEvent.click(screen.getByTestId("cross-goods-more-toggle"));
    const [card] = moreCards();
    const open = within(card).getAllByRole("button")[0];
    fireEvent.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByText("등급 근거 축")).toBeInTheDocument();
  });

  it("접근성 — 제목으로 이름 붙은 영역, 펼침 상태를 알리는 버튼, 아이콘은 숨김", () => {
    renderResult(withMore(resultWith(SAME), outside(3)));
    const title = "업종은 다르지만 표장이 닮은 상표 3건";
    const region = screen.getByRole("region", { name: title });
    expect(region).toBe(screen.getByTestId("cross-goods-more"));
    expect(within(region).getByRole("heading", { level: 2, name: title })).toBeInTheDocument();
    const toggle = within(region).getByRole("button", { name: title });
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const panel = within(region).getByTestId("cross-goods-more-panel");
    expect(toggle).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveAttribute("hidden");
    for (const icon of toggle.querySelectorAll("svg")) {
      expect(icon).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("규칙 — 제목과 한 줄", () => {
    expect(crossGoodsMoreTitle(7)).toBe("업종은 다르지만 표장이 닮은 상표 7건");
    expect(crossGoodsMoreNote(5, 5)).toBeNull();
    expect(crossGoodsMoreNote(3, 5)).toBeNull();
    expect(crossGoodsMoreNote(24, 5)).toBe("24건 가운데 표장이 가장 닮은 5건을 보여요.");
    // 수가 실린 후보보다 적게 와도 보이는 수보다 작게 적지 않는다
    expect(crossGoodsMore(withMore(resultWith(SAME), outside(3), 1))?.count).toBe(3);
  });
});

describe("계약 픽스처 그대로의 화면", () => {
  it("§3-1 문자상표(블루커피 + 카페): 가장 위 후보가 업종이 다른 닮은 상표 — 표시와 전체 등급 옆 한 줄", () => {
    const parsed = SearchV2ResponseSchema.parse(textFixture);
    expect(isCrossGoods(parsed.candidates[0])).toBe(true);
    expect(parsed.candidates[0].axes.x4).toBe(0);
    renderResult(parsed);
    expect(screen.getByTestId("cross-goods-overall")).toHaveTextContent(OVERALL);
    const flagged = parsed.candidates.filter(isCrossGoods).length;
    expect(screen.getAllByTestId("candidate-cross-goods")).toHaveLength(flagged);
    // 범위 안에 다 보여 접힌 칸은 없다
    expect(parsed.cross_goods_more).toEqual({ count: 0, candidates: [] });
    expect(screen.queryByTestId("cross-goods-more")).not.toBeInTheDocument();
    // 설명적 이름 안내(작은 안내)는 그대로 그 위에
    expect(screen.getByTestId("descriptive-notice")).toHaveAttribute("data-kind", "some-small");
  });

  it("§3-3 유명 상표(스타벅스 + 의류): 표시된 후보는 유명 상표 문구, 한 줄은 없고, 접힌 칸에 범위 밖 후보", () => {
    const parsed = SearchV2ResponseSchema.parse(famousFixture);
    expect(parsed.overall.famous_floor).toBe(true);
    renderResult(parsed);
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
    const shown = parsed.candidates.filter(isCrossGoods);
    expect(shown.length).toBeGreaterThan(0);
    for (const line of within(screen.getByRole("region", { name: "유사 상표 후보" })).getAllByTestId(
      "candidate-cross-goods-line",
    )) {
      expect(line).toHaveTextContent(FAMOUS);
    }
    const more = parsed.cross_goods_more!;
    expect(more.count).toBeGreaterThanOrEqual(more.candidates.length);
    expect(more.candidates.length).toBeGreaterThan(0);
    const toggle = screen.getByRole("button", { name: crossGoodsMoreTitle(more.count) });
    fireEvent.click(toggle);
    expect(moreCards()).toHaveLength(Math.min(more.candidates.length, CROSS_GOODS_MORE_LIMIT));
  });

  it("§3-2 이미지 예시(업종 없음)에는 표시도 한 줄도 칸도 없다", () => {
    const parsed = SearchV2ResponseSchema.parse(imageFixture);
    expect(parsed.cross_goods_more).toBeUndefined();
    expect(parsed.candidates.every((candidate) => candidate.cross_goods === undefined)).toBe(true);
    render(<ResultViewV2 result={parsed} queryPreview={null} queryHasName={false} onReset={vi.fn()} />);
    expect(screen.queryByText(BADGE)).not.toBeInTheDocument();
    expect(screen.queryByTestId("cross-goods-overall")).not.toBeInTheDocument();
    expect(screen.queryByTestId("cross-goods-more")).not.toBeInTheDocument();
  });
});
