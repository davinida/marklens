import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import NameCheckPanel from "@/components/NameCheckPanel";
import type { NameCheckResult } from "@/lib/contracts";

function resultWithCandidates(count: number): NameCheckResult {
  return {
    available: false,
    normalizedName: "BBQ",
    similarCount: count,
    exactCount: 1,
    exactRegisteredCount: 1,
    exactTitleCount: 2,
    candidates: Array.from({ length: count }, (_, index) => ({
      id: `40-${index + 1}`,
      name: `BBQ 후보 ${index + 1}`,
      applicationNumber: `40-${index + 1}`,
      registrationNumber: null,
      applicationStatus: "등록",
      applicantName: "테스트 출원인",
      rightHolderName: null,
      applicationDate: null,
      registrationDate: null,
      markType: null,
      niceClasses: ["43"],
      similarityCodes: [],
      viennaCodes: [],
      localImageUrl: null,
      exactTitleMatch: index === 0,
      isRegistered: true,
    })),
    candidatesReturned: count,
    candidatesTruncated: false,
    statusCounts: { "등록": count },
    message: "동일 명칭 후보가 있어요.",
    complete: true,
    scannedCount: count,
    totalFound: count,
    checkedAt: "2026-08-14T00:00:00Z",
    source: "KIPRIS fixture",
  };
}

describe("NameCheckPanel", () => {
  it("shows six candidates first and expands the result progressively", async () => {
    const user = userEvent.setup();
    render(<NameCheckPanel result={resultWithCandidates(12)} />);

    expect(screen.getByRole("button", { name: /BBQ 후보 6/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /BBQ 후보 7/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /후보 더 보기/ }));

    expect(screen.getByRole("button", { name: /BBQ 후보 12/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /후보 더 보기/ })).not.toBeInTheDocument();
  });
});
