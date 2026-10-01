import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import GoodsPicker from "@/components/GoodsPicker";
import { goodsCodeUnion, type SelectedGood } from "@/lib/goods";

const COFFEE = { name: "커피", nice_class: 30, similarity_codes: ["G0502"], matched_alias: null };
const CAFE = {
  name: "커피전문점업",
  nice_class: 43,
  similarity_codes: ["S120602", "G0502"],
  matched_alias: null,
};
const COFFEE_35 = {
  name: "커피 판매업(도소매·중개·대행)",
  nice_class: 35,
  similarity_codes: ["S2039"],
  matched_alias: "커피 소매업",
};
const CLASSES = {
  classes: [
    { nice_class: 25, title: "의류·신발", count: 3 },
    { nice_class: 30, title: "커피·과자", count: 1 },
    { nice_class: 35, title: "광고·사업관리·도소매업", count: 2 },
  ],
  total_entries: 6,
  source: "fixture",
};
const CAFE_PRESET = {
  id: "cafe",
  업종명: "카페",
  emoji: "☕",
  지정상품: [
    { name: "커피전문점업", nice_class: 43, similarity_codes: ["G0301", "G0502", "S120602"] },
    { name: "커피", nice_class: 30, similarity_codes: ["G0502"] },
    { name: "커피 소매업", nice_class: 35, similarity_codes: ["S2005"] },
  ],
};
const CHICKEN_PRESET = {
  id: "chicken",
  업종명: "치킨집",
  emoji: "🍗",
  hint: "치킨 자체는 양념통닭(29류)처럼 상품명으로 찾아요",
  지정상품: [
    { name: "식당업", nice_class: 43, similarity_codes: ["S120602"] },
    { name: "닭강정", nice_class: 29, similarity_codes: ["G0703"] },
  ],
};
const CLASS_25_PAGE_1 = [
  { name: "신발", nice_class: 25, similarity_codes: ["G4503"], matched_alias: null },
  { name: "의류", nice_class: 25, similarity_codes: ["G430301"], matched_alias: null },
];
const CLASS_25_PAGE_2 = [
  { name: "장갑", nice_class: 25, similarity_codes: ["G4501"], matched_alias: null },
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function mockFetch(handler: (url: URL) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) =>
      Promise.resolve(handler(new URL(String(input), "http://localhost"))),
    ),
  );
}

const searchFixture = (url: URL): Response => {
  if (url.pathname === "/api/goods/classes") return json(CLASSES);
  if (url.searchParams.get("q") === "커피") {
    return json({ query: "커피", matches: [COFFEE, CAFE, COFFEE_35], total: 3, offset: 0 });
  }
  if (url.searchParams.get("q") === "카페") {
    return json({
      query: "카페",
      matches: [{ name: "카페서비스업", nice_class: 43, similarity_codes: ["S120602"], matched_alias: null }],
      total: 1,
      offset: 0,
      presets: [CAFE_PRESET],
    });
  }
  if (url.searchParams.get("q") === "치킨") {
    return json({
      query: "치킨",
      matches: [{ name: "치킨너겟", nice_class: 29, similarity_codes: ["G0703"], matched_alias: null }],
      total: 1,
      offset: 0,
      presets: [CHICKEN_PRESET],
    });
  }
  if (url.searchParams.get("nice_class") === "25" && !url.searchParams.get("q")) {
    const offset = Number(url.searchParams.get("offset") ?? 0);
    return json({
      query: "",
      matches: offset === 0 ? CLASS_25_PAGE_1 : CLASS_25_PAGE_2,
      total: 3,
      offset,
    });
  }
  return json({ query: url.searchParams.get("q") ?? "", matches: [], total: 0, offset: 0 });
};

function Harness({ initial = [], max }: { initial?: SelectedGood[]; max?: number }) {
  const [value, setValue] = useState<SelectedGood[]>(initial);
  return (
    <form onSubmit={(event) => event.preventDefault()}>
      <GoodsPicker value={value} onChange={setValue} max={max} />
      <span data-testid="codes">{goodsCodeUnion(value).join(",")}</span>
    </form>
  );
}

const input = () => screen.getByRole("combobox", { name: "지정상품 검색" });
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("GoodsPicker", () => {
  beforeEach(() => mockFetch(searchFixture));

  it("waits for two characters and debounces typing into one request", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    // Safari 연락처 자동완성 아이콘 방지: 검색창은 type=search + autocomplete=off
    expect(input()).toHaveAttribute("type", "search");
    expect(input()).toHaveAttribute("autocomplete", "off");

    await user.type(input(), "커");
    expect(screen.getByText("2글자 이상 입력하면 검색해요.")).toBeVisible();
    await sleep(400);
    expect(fetch).not.toHaveBeenCalled();

    await user.type(input(), "피");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const url = String(vi.mocked(fetch).mock.calls[0][0]);
    expect(url).toContain("/api/goods/search?q=%EC%BB%A4%ED%94%BC");
    expect(url).toContain("limit=20");
    expect(await screen.findByRole("option", { name: /커피전문점업/ })).toBeVisible();
    expect(screen.getByText("고시 명칭: 커피 소매업")).toBeVisible();
  });

  it("adds from the dropdown, blocks duplicates, removes chips and unions the codes", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(input(), "커피");
    await user.click(await screen.findByRole("option", { name: /^커피 제30류/ }));
    expect(screen.getByRole("button", { name: "커피 제거" })).toBeVisible();
    expect(screen.getByTestId("codes")).toHaveTextContent("G0502");

    await user.click(screen.getByRole("option", { name: /커피전문점업/ }));
    expect(screen.getByRole("button", { name: "커피전문점업 제거" })).toBeVisible();
    expect(screen.getByTestId("codes")).toHaveTextContent("G0502,S120602");
    expect(screen.getByText("유사군 2개")).toBeVisible();

    await user.click(screen.getByRole("option", { name: /^커피 제30류/ }));
    expect(screen.getByRole("status")).toHaveTextContent("이미 고른 상품이에요.");
    expect(within(screen.getByRole("list", { name: "선택한 지정상품" })).getAllByRole("listitem")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "커피 제거" }));
    expect(screen.queryByRole("button", { name: "커피 제거" })).not.toBeInTheDocument();
    expect(screen.getByTestId("codes")).toHaveTextContent("G0502,S120602"); // 커피전문점업이 두 코드를 모두 가짐
    await user.click(screen.getByRole("button", { name: "커피전문점업 제거" }));
    expect(screen.getByTestId("codes")).toHaveTextContent("");
  });

  it("selects with the keyboard without submitting the surrounding form", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <GoodsPicker value={[]} onChange={vi.fn()} />
      </form>,
    );
    const onChange = vi.fn();
    render(<GoodsPicker value={[]} onChange={onChange} />);

    const boxes = screen.getAllByRole("combobox", { name: "지정상품 검색" });
    await user.type(boxes[0], "커피");
    await screen.findAllByRole("option", { name: /커피전문점업/ });
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(boxes[1], "커피");
    await waitFor(() => expect(boxes[1]).toHaveAttribute("aria-expanded", "true"));
    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith([
      { name: "커피전문점업", nice_class: 43, similarity_codes: ["S120602", "G0502"] },
    ]);
    await user.keyboard("{Escape}");
    expect(boxes[1]).toHaveAttribute("aria-expanded", "false");
  });

  it("caps the selection with a notice", async () => {
    const user = userEvent.setup();
    const full: SelectedGood[] = [
      { name: "의류", nice_class: 25, similarity_codes: ["G430301"] },
      { name: "신발", nice_class: 25, similarity_codes: ["G4503"] },
    ];
    render(<Harness initial={full} max={2} />);

    await user.type(input(), "커피");
    await user.click(await screen.findByRole("option", { name: /^커피 제30류/ }));
    expect(screen.getByRole("status")).toHaveTextContent("지정상품은 최대 2개까지 고를 수 있어요.");
    expect(screen.queryByRole("button", { name: "커피 제거" })).not.toBeInTheDocument();
  });

  it("explains a 429 and shows the total hint when results are cut", async () => {
    const user = userEvent.setup();
    mockFetch(() => json({ detail: "too many" }, 429));
    render(<Harness />);
    await user.type(input(), "커피");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "요청이 잦아요. 잠시 후 다시 시도해 주세요.",
    );

    mockFetch(() =>
      json({
        query: "업",
        matches: Array.from({ length: 20 }, (_, i) => ({
          name: `상품${i}업`,
          nice_class: 35,
          similarity_codes: ["S2000"],
          matched_alias: null,
        })),
        total: 53991,
        offset: 0,
      }),
    );
    await user.clear(input());
    await user.type(input(), "판매업");
    expect(await screen.findByText("53,991건 중 20건 — 더 구체적으로 입력해 보세요.")).toBeVisible();
  });

  it("browses a class listing without a query and pages with 더 보기", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "분류로 찾기" }));
    // 모바일 기본: 서비스(35~45류) 묶음은 펼쳐져 있고 상품(1~34류) 묶음은 접혀 있다
    expect(await screen.findByRole("button", { name: /제35류 광고·사업관리·도소매업/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /제25류 의류·신발/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "상품(1~34류)" }));
    await user.click(await screen.findByRole("button", { name: /제25류 의류·신발/ }));
    const list = await screen.findByRole("list", { name: "제25류 상품 목록" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("2/3건")).toBeVisible();
    const listingUrl = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://localhost");
    expect(listingUrl.searchParams.get("q")).toBeNull();
    expect(listingUrl.searchParams.get("nice_class")).toBe("25");

    await user.click(screen.getByRole("button", { name: /더 보기/ }));
    expect(await screen.findByRole("button", { name: "장갑 추가" })).toBeVisible();
    const moreUrl = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://localhost");
    expect(moreUrl.searchParams.get("offset")).toBe("2");
    expect(screen.queryByRole("button", { name: /더 보기/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "장갑 추가" }));
    expect(screen.getByRole("button", { name: "장갑 제거" })).toBeVisible();
    expect(screen.getByTestId("codes")).toHaveTextContent("G4501");

    // 류를 고른 채 검색하면 그 류 안에서 찾는다(nice_class 전달)
    await user.type(input(), "커피");
    await waitFor(() => {
      const url = new URL(String(vi.mocked(fetch).mock.calls.at(-1)![0]), "http://localhost");
      expect(url.searchParams.get("q")).toBe("커피");
      expect(url.searchParams.get("nice_class")).toBe("25");
    });
  });

  it("shows a business preset card and adds every item at once", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(input(), "카페");
    const card = await screen.findByRole("region", { name: "카페 업종 세트" });
    expect(card).toHaveTextContent("카페 업종 — 커피전문점업(43류) · 커피(30류) · 커피 소매업(35류)");
    await user.click(within(card).getByRole("button", { name: "3개 모두 추가" }));

    for (const name of ["커피전문점업", "커피", "커피 소매업"]) {
      expect(screen.getByRole("button", { name: `${name} 제거` })).toBeVisible();
    }
    expect(screen.getByTestId("codes")).toHaveTextContent("G0301,G0502,S120602,S2005");
    expect(screen.getByText("유사군 4개")).toBeVisible();
    expect(within(card).getByRole("button", { name: "모두 선택됨" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "커피 선택됨" })).toBeDisabled();
    // 세트로 추가한 항목도 개별 제거된다(칩을 누르면 입력창이 blur 돼 드롭다운이 닫힌다)
    await user.click(screen.getByRole("button", { name: "커피 제거" }));
    expect(screen.queryByRole("button", { name: "커피 제거" })).not.toBeInTheDocument();
    await user.click(input()); // 다시 포커스하면 같은 결과로 드롭다운이 열리고 커피는 다시 추가 가능
    const reopened = await screen.findByRole("region", { name: "카페 업종 세트" });
    expect(within(reopened).getByRole("button", { name: "커피 추가" })).toBeEnabled();
  });

  it("adds a single preset item and applies the cap to 모두 추가", async () => {
    const user = userEvent.setup();
    render(<Harness max={2} />);

    await user.type(input(), "카페");
    const card = await screen.findByRole("region", { name: "카페 업종 세트" });
    await user.click(within(card).getByRole("button", { name: "커피 추가" }));
    expect(screen.getByRole("button", { name: "커피 제거" })).toBeVisible();

    await user.click(within(card).getByRole("button", { name: "3개 모두 추가" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "지정상품은 최대 2개까지라 1개는 추가하지 못했어요.",
    );
    expect(within(screen.getByRole("list", { name: "선택한 지정상품" })).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "커피전문점업 제거" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "커피 소매업 제거" })).not.toBeInTheDocument();
  });

  it("offers frequent businesses when empty and opens the set when a chip is clicked", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const group = screen.getByRole("group", { name: "자주 찾는 업종" });
    expect(within(group).getAllByRole("button")).toHaveLength(12);
    await user.click(within(group).getByRole("button", { name: "치킨집" }));
    expect(input()).toHaveValue("치킨");
    expect(screen.queryByRole("group", { name: "자주 찾는 업종" })).not.toBeInTheDocument();
    const card = await screen.findByRole("region", { name: "치킨집 업종 세트" });
    expect(card).toHaveTextContent("식당업(43류) · 닭강정(29류)");
    expect(card).toHaveTextContent("치킨 자체는 양념통닭(29류)처럼 상품명으로 찾아요");
    expect(String(vi.mocked(fetch).mock.calls.at(-1)![0])).toContain("q=%EC%B9%98%ED%82%A8");
  });

  it("explains similarity groups on demand", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[{ name: "커피", nice_class: 30, similarity_codes: ["G0502"] }]} />);

    expect(screen.queryByText(/특허청이 서로 비슷한 상품끼리/)).not.toBeInTheDocument();
    const help = screen.getByRole("button", { name: "유사군 설명" });
    await user.click(help);
    expect(help).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText(
        "유사군: 특허청이 서로 비슷한 상품끼리 묶어 둔 심사 기준 그룹이에요. 같은 그룹이면 상품이 비슷하다고 봐요.",
      ),
    ).toBeVisible();
    await user.click(help);
    expect(screen.queryByText(/특허청이 서로 비슷한 상품끼리/)).not.toBeInTheDocument();
  });
});

