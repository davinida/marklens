import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SemanticMatchesSection from "@/components/SemanticMatchesSection";
import { SemanticSearchResponseSchema } from "@/lib/contracts";

const RESULT = SemanticSearchResponseSchema.parse({
  query: { name: "왕", has_meaning: true, text: "왕" },
  matches: [
    {
      rank: 1,
      score: 0.8072,
      출원번호: "4020210000001",
      상표한글명: "KING",
      이미지URL: "/images/4020210000001.png",
      출원인: "킹 코퍼레이션",
      류: [25],
    },
    {
      rank: 2,
      score: 0.6,
      출원번호: "4020210000002",
      상표한글명: "임금",
      이미지URL: null,
      출원인: null,
      류: [],
    },
  ],
  searched_count: 595,
  excluded_no_meaning: 352,
  params: { top_k: 5, min_score: 0.55 },
  threshold: 0.55,
  axis: "X3",
  note: "관념(의미) 유사도만 반영한 참고 정보",
  model: "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
});

describe("SemanticMatchesSection", () => {
  it("renders the matches with score bars and dataset scope", () => {
    render(<SemanticMatchesSection phase={{ name: "result", data: RESULT }} />);

    expect(screen.getByRole("heading", { name: "관념 유사 후보" })).toBeVisible();
    expect(screen.getByText("X3 관념 유사도 · DB 595건 대상 · 참고 정보")).toBeVisible();
    expect(screen.getByText("KING")).toBeVisible();
    expect(screen.getByText("80.7%")).toBeVisible();
    expect(screen.getByText("60%")).toBeVisible();
    expect(screen.getAllByText("관념 유사도")).toHaveLength(2);
    expect(screen.getByText(/4020210000001/)).toBeVisible();
    expect(screen.getByRole("img", { name: "KING 등록상표" })).toHaveAttribute(
      "src",
      "/api/images/4020210000001.png",
    );
    expect(screen.getByRole("img", { name: "임금 상표 이미지 없음" })).toBeVisible();
    expect(screen.getByText(/관념\(의미\) 유사도만 반영한 참고 정보/)).toBeVisible();
  });

  it("shows the empty state with the score floor", () => {
    render(
      <SemanticMatchesSection
        phase={{ name: "result", data: { ...RESULT, matches: [] } }}
      />,
    );

    expect(screen.getByText("유사도 55% 이상인 등록상표가 없습니다.")).toBeVisible();
  });

  it("explains a coined name instead of listing matches", () => {
    render(
      <SemanticMatchesSection
        phase={{
          name: "result",
          data: {
            ...RESULT,
            query: { name: "스타벅스", has_meaning: false, text: "" },
            matches: [],
            note: "관념 없음(조어)",
          },
        }}
      />,
    );

    expect(
      screen.getByText("입력한 이름에 사전적 의미가 없어(조어) 관념을 비교하지 않았어요."),
    ).toBeVisible();
    expect(screen.getByText(/관념 없음\(조어\)/)).toBeVisible();
    expect(screen.queryByText(/이상인 등록상표가 없습니다/)).not.toBeInTheDocument();
  });

  it("separates loading and error states from the name check", () => {
    const { rerender } = render(<SemanticMatchesSection phase={{ name: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("관념 유사도를 계산하는 중이에요.");

    rerender(
      <SemanticMatchesSection
        phase={{ name: "error", message: "관념 유사도를 계산하지 못했어요." }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("관념 유사도를 계산하지 못했어요.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
