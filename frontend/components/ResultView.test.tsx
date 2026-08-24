import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResultView, { similarityPercentage } from "@/components/ResultView";
import { SearchResponseSchema } from "@/lib/contracts";

describe("ResultView canonical status", () => {
  it("does not round a score across a visual status threshold", () => {
    expect(similarityPercentage(0.7499)).toBe(74.9);
    expect(similarityPercentage(0.75)).toBe(75);
    expect(similarityPercentage(0.5499)).toBe(54.9);
    expect(similarityPercentage(0.55)).toBe(55);
  });

  it("uses NO_CLOSE_MATCH ahead of the ambiguous legacy LOW code", () => {
    const result = SearchResponseSchema.parse({
      grade: {
        status_code: "NO_CLOSE_MATCH",
        status_name: "가까운 시각 후보 미확인",
        uncertain: false,
        uncertainty_reasons: [],
        scored_candidate_count: 20,
        threshold_version: "visual-v2-uncalibrated",
        scope: "visual_similarity_only",
        calibrated: false,
        legal_conclusion: false,
        grade_code: "LOW",
        grade_name: "가까운 후보 미확인",
        message: "데이터 범위 밖의 권리가 없다는 뜻은 아닙니다.",
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
        출원일자_범위: "2026",
        데이터_기준: "테스트",
        생성일자: "2026-08-14",
      },
      index_size: 1,
      top_k_requested: 5,
      top_k_returned: 1,
      scoring_k: 20,
      research_beta: true,
    });

    render(
      <ResultView
        result={result}
        queryPreview={null}
        nameCheck={{
          available: null,
          normalizedName: "BBQ",
          similarCount: 0,
          exactCount: 0,
          exactRegisteredCount: 0,
          exactTitleCount: 0,
          candidates: [],
          candidatesReturned: 0,
          candidatesTruncated: false,
          statusCounts: {},
          message: "일부 결과만 확인했어요.",
          complete: false,
          scannedCount: 20,
          totalFound: 40,
          checkedAt: null,
          source: "KIPRIS fixture",
        }}
        onReset={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "가까운 시각 후보를 찾지 못했어요" }),
    ).toBeVisible();
    expect(screen.getByText("가까운 시각 후보 미확인")).toBeVisible();
    expect(
      screen.getAllByRole("img", { name: "상표 이미지 없음" }).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("분석 근거 대시보드")).toBeVisible();
    expect(screen.getByText("후보 점수 분포")).toBeVisible();
    expect(screen.getByText("일부 조회됨")).toBeVisible();
    expect(screen.getByText("동일 명칭 등록상표 검색 일부 확인")).toBeVisible();
    expect(
      document.querySelector("[data-name-evidence] + [data-visual-candidates]"),
    ).toBeInTheDocument();
    expect(screen.getByText("비교 축")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "다른 로고 비교하기" }),
    ).toBeVisible();
  });
});
