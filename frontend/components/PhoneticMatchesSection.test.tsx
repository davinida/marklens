import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PhoneticMatchesSection from "@/components/PhoneticMatchesSection";
import { PhoneticSearchResponseSchema } from "@/lib/contracts";

const RESULT = PhoneticSearchResponseSchema.parse({
  query: { name: "스타박스", has_pronunciation: true, candidates: ["스타박스"] },
  matches: [
    {
      rank: 1,
      similarity: 0.9636,
      출원번호: "4020210000001",
      상표한글명: "스타벅스",
      이미지URL: "/images/4020210000001.png",
      출원인: "스타벅스 코포레이션",
      류: [43],
    },
    {
      rank: 2,
      similarity: 0.7,
      출원번호: "4020210000002",
      상표한글명: "스타박",
      이미지URL: null,
      출원인: null,
      류: [],
    },
  ],
  searched_count: 947,
  excluded_no_pronunciation: 153,
  params: { top_k: 5, min_similarity: 0.5 },
  axis: "X1",
  note: "호칭(발음) 유사도만 반영한 참고 정보",
});

describe("PhoneticMatchesSection", () => {
  it("renders the matches with score bars and dataset scope", () => {
    render(<PhoneticMatchesSection phase={{ name: "result", data: RESULT }} />);

    expect(
      screen.getByRole("heading", { name: "발음(호칭)이 비슷한 등록상표" }),
    ).toBeVisible();
    expect(screen.getByText("X1 호칭 유사도 · DB 947건 대상 · 참고 정보")).toBeVisible();
    expect(screen.getByText("스타벅스")).toBeVisible();
    expect(screen.getByText("96.3%")).toBeVisible();
    expect(screen.getByText("70%")).toBeVisible();
    expect(screen.getByText(/4020210000001/)).toBeVisible();
    expect(screen.getByRole("img", { name: "스타벅스 등록상표" })).toHaveAttribute(
      "src",
      "/api/images/4020210000001.png",
    );
    expect(screen.getByRole("img", { name: "스타박 상표 이미지 없음" })).toBeVisible();
  });

  it("shows the empty state with the similarity floor", () => {
    render(
      <PhoneticMatchesSection
        phase={{ name: "result", data: { ...RESULT, matches: [] } }}
      />,
    );

    expect(screen.getByText("유사도 50% 이상인 등록상표가 없습니다.")).toBeVisible();
  });

  it("separates loading and error states from the name check", () => {
    const { rerender } = render(<PhoneticMatchesSection phase={{ name: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("발음 유사도를 계산하는 중이에요.");

    rerender(
      <PhoneticMatchesSection
        phase={{ name: "error", message: "발음 유사도를 계산하지 못했어요." }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("발음 유사도를 계산하지 못했어요.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
