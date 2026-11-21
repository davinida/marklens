import type { StatusCode } from "@/lib/contracts";

// 시각 유사 4상태(백엔드 scoring.score_results 의 status_code → v2 overall.visual_status)의
// 헤드라인·색. 결과 화면 v2 가 "시각 유사 상태" 줄에 쓴다.
export const GRADE_VIEW: Record<
  StatusCode,
  {
    mark: string;
    headline: string;
    text: string;
    border: string;
    bg: string;
    pill: string;
    meter: string;
  }
> = {
  STRONG_MATCH: {
    mark: "!",
    headline: "매우 닮은 등록상표가 있어요",
    text: "text-caution-deep",
    border: "border-caution",
    bg: "bg-caution-bg",
    pill: "bg-caution-deep text-white",
    meter: "bg-caution",
  },
  POSSIBLE_MATCH: {
    mark: "!",
    headline: "확인이 필요한 비슷한 상표가 있어요",
    text: "text-review-deep",
    border: "border-review",
    bg: "bg-review-bg",
    pill: "bg-review-deep text-white",
    meter: "bg-review",
  },
  WEAK_MATCH: {
    mark: "i",
    headline: "가까운 등록상표를 확인해 보세요",
    text: "text-sub",
    border: "border-low",
    bg: "bg-low-bg",
    pill: "bg-low text-white",
    meter: "bg-low",
  },
  NO_CLOSE_MATCH: {
    mark: "i",
    headline: "가까운 시각 후보를 찾지 못했어요",
    text: "text-blue-dark",
    border: "border-blue-dark",
    bg: "bg-blue-bg",
    pill: "bg-blue-dark text-white",
    meter: "bg-blue-dark",
  },
};
