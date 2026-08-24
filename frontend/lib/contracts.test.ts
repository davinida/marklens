// @vitest-environment node

import { describe, expect, it } from "vitest";
import { parseNameCheckResponse, SearchResponseSchema } from "@/lib/contracts";

describe("parseNameCheckResponse", () => {
  it("preserves additive completeness metadata", () => {
    expect(
      parseNameCheckResponse(
        {
          available: false,
          normalized_name: "MARK LENS",
          similar_count: 4,
          exact_count: 1,
          examples: ["MARKLENS"],
          message: "확인이 필요해요.",
          complete: false,
          scanned_count: 30,
          total_found: 120,
          checked_at: "2026-08-14T00:00:00Z",
          source: "KIPRIS",
        },
        "mark lens",
      ),
    ).toMatchObject({
      available: null,
      normalizedName: "MARK LENS",
      similarCount: 4,
      exactCount: 1,
      complete: false,
      scannedCount: 30,
      totalFound: 120,
    });
  });

  it("does not claim completeness when the backend omits it", () => {
    const result = parseNameCheckResponse(
      { available: true, message: "일치 없음" },
      " MarkLens ",
    );

    expect(result.complete).toBeNull();
    expect(result.scannedCount).toBeNull();
    expect(result.normalizedName).toBe("MarkLens");
  });

  it("preserves the extended legacy coverage fields", () => {
    const result = parseNameCheckResponse(
      {
        query: "마크렌즈",
        total_found: 7,
        scanned_count: 3,
        registered_count: 3,
        exact_registered_count: 0,
        complete: false,
        checked_at: "2026-08-14T00:00:00Z",
        source: "KIPRIS mock",
        cached: true,
        message: "동일 이름 없음",
      },
      "마크렌즈",
    );

    expect(result).toMatchObject({
      available: null,
      similarCount: 3,
      exactCount: 0,
      complete: false,
      scannedCount: 3,
      checkedAt: "2026-08-14T00:00:00Z",
      source: "KIPRIS mock",
    });
  });

  it("only marks a completed legacy name search as available", () => {
    const result = parseNameCheckResponse(
      {
        query: "마크렌즈",
        total_found: 0,
        scanned_count: 0,
        registered_count: 0,
        exact_registered_count: 0,
        complete: true,
        checked_at: null,
        source: "fixture",
        cached: false,
        message: "동일 이름 없음",
      },
      "마크렌즈",
    );

    expect(result.available).toBe(true);
  });

  it("normalizes canonical KIPRIS candidates and keeps exact counts separate", () => {
    const result = parseNameCheckResponse(
      {
        query: "BBQ",
        total_found: 12,
        scanned_count: 12,
        registered_count: 5,
        exact_registered_count: 1,
        exact_title_count: 3,
        complete: true,
        checked_at: "2026-08-14T00:00:00Z",
        source: "KIPRIS",
        cached: false,
        message: "동일 명칭의 선행 등록상표가 있습니다.",
        candidates_returned: 1,
        candidates_truncated: true,
        status_counts: { "등록": 5, "소멸": 4, "거절": 3 },
        candidates: [
          {
            application_number: "4020260012345",
            registration_number: "4012345670000",
            title: "BBQ",
            status: "등록",
            applicant: "제너시스비비큐",
            right_holder: "제너시스비비큐",
            application_date: "20260101",
            registration_date: "20260701",
            mark_type: "일반상표",
            nice_classes: ["29", "43"],
            vienna_codes: ["27.05.01"],
            similarity_codes: ["G0301"],
            exact_title_match: true,
            is_registered: true,
            local_image_url: "/images/bbq.png",
          },
        ],
      },
      "BBQ",
    );

    expect(result).toMatchObject({
      exactRegisteredCount: 1,
      exactTitleCount: 3,
      candidatesReturned: 1,
      candidatesTruncated: true,
      statusCounts: { "등록": 5, "소멸": 4, "거절": 3 },
      candidates: [
        {
          name: "BBQ",
          applicationNumber: "4020260012345",
          niceClasses: ["29", "43"],
          exactTitleMatch: true,
          isRegistered: true,
          localImageUrl: "/images/bbq.png",
        },
      ],
    });
  });
});

describe("SearchResponseSchema", () => {
  it("rejects a response with an unknown grade", () => {
    expect(
      SearchResponseSchema.safeParse({
        grade: {
          grade_code: "UNKNOWN",
          grade_name: "?",
          message: "?",
          top1_similarity: 0.1,
          separability_a: 0,
          separability_b: 0,
        },
        matches: [],
        dataset_info: {
          총_상표수: 0,
          출원일자_범위: "-",
          데이터_기준: "-",
          생성일자: "-",
        },
        index_size: 0,
        top_k_requested: 5,
        top_k_returned: 0,
      }).success,
    ).toBe(false);
  });
});
