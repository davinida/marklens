"use client";

import { useId, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ImageIcon,
  RotateCcw,
  Wand2,
} from "lucide-react";
import { imageUrl } from "@/lib/api";
import type { SearchV2Candidate, SearchV2Grade, SearchV2Response } from "@/lib/contracts";
import DescriptiveNotice from "@/components/DescriptiveNotice";
import FamousBanner, {
  FAMOUS_LEVEL_DESCRIPTIVE,
  famousBannerLevel,
  famousBannerState,
  famousFloorReason,
} from "@/components/FamousBanner";
import {
  CROSS_GOODS_TEXT,
  crossGoodsLine,
  crossGoodsMore,
  crossGoodsMoreNote,
  crossGoodsMoreTitle,
  showsCrossGoodsOverallLine,
} from "@/lib/crossGoods";
import { NOTICE_TEXT, showsWholeNameLine } from "@/lib/descriptiveNotice";
import { ANNOUNCE_TEXT } from "@/lib/announce";
import { josaEulReul, josaEunNeun, josaEuroRo } from "@/lib/josa";
import {
  REFERENCE_NOTE,
  logoOnlyNoticeKind,
  splitCaveats,
  type QuerySummaryInput,
} from "@/lib/resultExtras";
import { LogoOnlyNotice, PhotoNotice, QuerySummary } from "@/components/ResultExtras";
// v1 결과 화면의 시각 4상태 문구(API 계약 v2 §4-5: v1 과 같은 문구로 보여 준다)
import { GRADE_VIEW as VISUAL_STATUS_VIEW } from "@/components/visualStatusView";

// API 계약 v2 §4-4
const GRADE_VIEW: Record<
  "안전" | "주의" | "검토 권장" | "위험",
  {
    text: string;
    border: string;
    bg: string;
    pill: string;
    bar: string;
    description: string;
    /** 로고만 넣은 검색(이름이 없고 이미지가 있는 질의)의 설명 */
    logoDescription: string;
  }
> = {
  안전: {
    text: "text-low-text",
    border: "border-low",
    bg: "bg-low-bg",
    pill: "bg-low text-white",
    bar: "bg-low",
    description: "비교한 상표 가운데 가까운 것을 찾지 못했어요. 안전하다는 뜻은 아니에요",
    logoDescription: "로고가 가까운 상표를 찾지 못했어요. 안전하다는 뜻은 아니에요",
  },
  주의: {
    text: "text-warn-deep",
    border: "border-warn",
    bg: "bg-warn-bg",
    pill: "bg-warn-deep text-white",
    bar: "bg-warn",
    description: "조금 닮은 상표가 있어요",
    logoDescription: "로고가 조금 닮은 상표가 있어요",
  },
  "검토 권장": {
    text: "text-review-text",
    border: "border-review",
    bg: "bg-review-bg",
    pill: "bg-review-deep text-white",
    bar: "bg-review",
    description: "닮은 선행 상표가 있을 수 있어요. 전문가 검토를 권해요",
    logoDescription: "로고가 닮은 선행 상표가 있을 수 있어요. 전문가 검토를 권해요",
  },
  위험: {
    text: "text-caution-deep",
    border: "border-caution",
    bg: "bg-caution-bg",
    pill: "bg-caution-deep text-white",
    bar: "bg-caution",
    description: "많이 닮은 선행 상표가 있어요",
    logoDescription: "로고가 많이 닮은 선행 상표가 있어요",
  },
};

/** 등급 한 줄 설명(§4-4) — 축 수를 말하지 않는다. 로고만 넣은 검색(이름이 없고 이미지가 있는
 *  질의)은 로고를 견준 것임을 말한다. */
export function gradeDescription(grade: SearchV2Grade, logoOnly: boolean): string {
  return logoOnly ? GRADE_VIEW[grade].logoDescription : GRADE_VIEW[grade].description;
}

const AXIS_VALUE_LABEL: Record<"x1" | "x2_text" | "x2_img" | "x3" | "x4", string> = {
  x1: "호칭",
  x2_text: "철자",
  x2_img: "이미지",
  x3: "관념",
  x4: "상품",
};
const AXIS_VALUE_ORDER = ["x1", "x2_text", "x2_img", "x3", "x4"] as const;

const CONTRIBUTION_LABEL: Record<"X1" | "X2" | "X3" | "X4" | "요부", string> = {
  X1: "호칭(발음)",
  X2: "외관(철자·이미지)",
  X3: "관념(뜻)",
  X4: "지정상품",
  요부: "요부(식별력)",
};
const CONTRIBUTION_ORDER = ["X1", "X2", "X3", "X4", "요부"] as const;

// 규칙 사유(§4-1) — 카드의 최종 등급이 무엇이든 참인 문장만 쓴다. 응답에는 규칙을 적용하기 전 등급이
// 없어 규칙이 실제로 등급을 바꿨는지 화면은 알 수 없다. 하한 규칙은 "… 이상으로 봤어요", 상한 규칙은
// "… 더 높이지 않았어요" — 특정 등급으로 올렸다·내렸다고 단정하지 않는다.
const RULE_TRIGGER_TEXT: Record<string, string> = {
  standalone_x1: "발음이 거의 같아서 검토 권장 이상으로 봤어요",
  standalone_x2_text: "철자가 매우 비슷해서 검토 권장 이상으로 봤어요",
  standalone_x3: "뜻이 매우 비슷해서 검토 권장 이상으로 봤어요",
  figure_x2_img:
    "도형이 매우 비슷해서 검토 권장 이상으로 봤어요. 도형 비교는 검증 데이터가 적어 참고용이에요",
  nameless_floor: "로고만 봤을 때의 등급이 더 높아서 그 등급 이상으로 봤어요",
  goods_floor: "업종이 겹쳐서 로고만 봤을 때의 등급 이상으로 봤어요",
  goods_floor_named: "업종이 겹쳐서 업종 없이 봤을 때의 등급 이상으로 봤어요",
  goods_cap: "업종이 달라서 등급을 더 높이지 않았어요",
};
/** 문구가 없는 규칙 코드 — 코드를 그대로 보이지 않는다. */
const RULE_TRIGGER_FALLBACK = "따로 정한 규칙이 적용됐어요";
/** 사유 문장이 등급을 말하는 하한 규칙 — 카드의 등급이 그보다 낮으면 그 문장을 보이지 않는다. */
const RULE_TRIGGER_FLOOR: Record<string, SearchV2Grade> = {
  standalone_x1: "검토 권장",
  standalone_x2_text: "검토 권장",
  standalone_x3: "검토 권장",
  figure_x2_img: "검토 권장",
};
/** 업종 상한 — 같은 카드에 "업종 다름" 표시가 있으면 숨긴다(업종 얘기를 두 번 하지 않는다). */
const RULE_TRIGGER_GOODS_CAP = "goods_cap";

/** 카드에 보일 규칙 사유 문장 — 규칙 코드 순서대로, 같은 문장은 한 번만. */
export function ruleTriggerLines(
  triggers: string[],
  grade: SearchV2Grade,
  hasCrossGoodsBadge: boolean,
): string[] {
  const lines: string[] = [];
  for (const trigger of triggers) {
    if (trigger === RULE_TRIGGER_GOODS_CAP && hasCrossGoodsBadge) continue;
    const floor = RULE_TRIGGER_FLOOR[trigger];
    if (floor && SCALE_GRADES.indexOf(grade) < SCALE_GRADES.indexOf(floor)) continue;
    const line = RULE_TRIGGER_TEXT[trigger] ?? RULE_TRIGGER_FALLBACK;
    if (!lines.includes(line)) lines.push(line);
  }
  return lines;
}

/** 유형 고치기 버튼의 글자 — "문자로 고치기"·"도형으로 고치기"·"결합으로 고치기". */
export function retypeLabel(type: string): string {
  return `${type}${josaEuroRo(type)} 고치기`;
}

// API 계약 v2 §2-5 FIGURE_LOW_DATA·§4-5 — 후보 카드의 도형 참고 문구(응답 caveat 과 같은 문장)
const FIGURE_CAVEAT_TEXT =
  "로고 파일끼리 비교한 결과예요. 도형 유사는 검증 데이터가 적어 참고용이에요";
// API 계약 v2 §4-4 — 이름 없는 질의 안내
const NAMELESS_GUIDANCE = "상표명·업종을 넣으면 더 정확하게 판단해요";

// 이름 없는 판단 = risk.pattern(또는 overall.pattern)이 "noname:" 으로 시작(계약 v2 §2-2). 요청에
// 이름을 넣었는지와 상관없이 응답의 계수 집합으로 판별한다 — 이름 있는 질의도 이름 없는 후보와는
// 이름 없는 판단이 된다. 이름 있는·없는 판단은 위험도 % 눈금이 달라 %를 보이지 않는다.
const NAMELESS_PREFIX = "noname:";

type GradeCuts = { 주의: number | null; "검토 권장": number | null; 위험: number | null };

export function isNamelessPattern(pattern: string | null | undefined): boolean {
  return typeof pattern === "string" && pattern.startsWith(NAMELESS_PREFIX);
}

/** 그 판단의 등급 하한 — 이름 없는 판단은 meta.thresholds.nameless[pattern], 그 밖은 grade. */
export function thresholdsFor(
  meta: SearchV2Response["meta"],
  pattern: string | null | undefined,
): GradeCuts {
  if (isNamelessPattern(pattern)) {
    const cuts = meta.thresholds.nameless[pattern as string];
    if (cuts) return cuts;
  }
  return meta.thresholds.grade;
}

const SCALE_GRADES: SearchV2Grade[] = ["안전", "주의", "검토 권장", "위험"];

/** 등급 눈금(§4-4) — 구간 폭은 그 판단의 하한. 하한이 null 인 등급은 위험도로는 닿지 않아 구간이
 *  없다. 이름 있는 판단만 위험도 위치(표식)를 보인다. */
function GradeScale({
  cuts,
  grade,
  prob,
}: {
  cuts: GradeCuts;
  grade: SearchV2Grade;
  prob: number | null;
}) {
  const bands: { grade: SearchV2Grade; start: number; end: number }[] = [];
  let start = 0;
  let current: SearchV2Grade = "안전";
  for (const next of SCALE_GRADES.slice(1)) {
    const cut = cuts[next as keyof GradeCuts];
    if (cut === null) continue;
    bands.push({ grade: current, start, end: cut });
    start = cut;
    current = next;
  }
  bands.push({ grade: current, start, end: 1 });
  const label = bands.map((band) => band.grade).join(" · ");
  return (
    <div data-testid="grade-scale" className="relative mt-2 h-2 w-full max-w-[240px]">
      <div
        className="flex h-full w-full overflow-hidden rounded-full"
        role="img"
        aria-label={`등급 눈금: ${label}${grade ? ` — 지금 ${grade}` : ""}`}
      >
        {bands.map((band) => (
          <span
            key={band.grade}
            data-grade={band.grade}
            className={`h-full ${GRADE_VIEW[band.grade].bar} ${band.grade === grade ? "" : "opacity-30"}`}
            style={{ width: `${Math.max(0, band.end - band.start) * 100}%` }}
          />
        ))}
      </div>
      {prob !== null && (
        <span
          data-testid="grade-scale-marker"
          aria-hidden
          className="absolute -top-0.5 h-3 w-0.5 rounded-full bg-ink"
          style={{ left: `${Math.min(1, Math.max(0, prob)) * 100}%` }}
        />
      )}
    </div>
  );
}

const SIDE_LABEL: Record<"query" | "candidate" | "both", string> = {
  query: "입력",
  candidate: "후보",
  both: "양쪽",
};

const REASON_PHRASES: [prefix: string, phrase: string][] = [
  ["1호 보통명칭", "흔한 말"],
  ["3호 기술적 표장", "상품을 설명하는 말"],
  ["4호 지명", "지명"],
  ["5호 흔한 성", "흔한 성씨"],
  ["6호 간단 표장", "간단한 표장"],
  ["일반어", "흔한 말"],
  ["다수 등록", "흔한 말"],
];

function reasonPhrase(reason: string): string {
  const first = reason.split("·")[0] ?? reason;
  for (const [prefix, phrase] of REASON_PHRASES) {
    if (first.includes(prefix) || reason.includes(prefix)) return phrase;
  }
  return "식별력이 약한 말";
}

// 조사는 lib/josa.ts(은/는·으로/로·을/를 — 한글 음절로 끝나지 않으면 받침 없는 것으로 본다)

/** 0–1 점수를 % 정수로 — 내림. 기준(시각 상태 0.75·도형 규칙 0.9·단독 임계값 0.98 등)을 넘지 않은 값이
 *  넘은 것처럼 보이지 않게 한다(0.7499 → 74%). 1e-9 는 0.57 * 100 = 56.99… 같은 이진 표현 오차 보정으로,
 *  응답 값의 자릿수(소수 3–4자리)보다 훨씬 작다. */
export function toPercent(value: number): number {
  return Math.floor(Math.max(0, Math.min(1, value)) * 100 + 1e-9);
}

/** API 계약 v2 §4-2 — 제외 토큰을 side(query/candidate/both)별로 묶어 한 줄씩 문장을 만든다. */
function buildSalientSentences(
  salient: SearchV2Candidate["salient"],
  hasQueryName: boolean,
): string[] {
  const groups: Record<"query" | "candidate" | "both", typeof salient.removed> = {
    query: [],
    candidate: [],
    both: [],
  };
  for (const entry of salient.removed) groups[entry.side].push(entry);

  const sentences: string[] = [];
  for (const side of ["query", "candidate", "both"] as const) {
    const items = groups[side];
    if (!items.length) continue;
    const subjectTokens = side === "candidate" ? salient.candidate_tokens : salient.query_tokens;
    const removedText = items.map((item) => item.token).join("·");
    const phrase = reasonPhrase(items[0].reason);
    const j1 = josaEunNeun(removedText);
    if (!subjectTokens.length) {
      sentences.push(`'${removedText}'${j1} ${phrase}이라 제외했어요`);
      continue;
    }
    const subjectText = subjectTokens.join("·");
    const j2 = josaEuroRo(subjectText);
    sentences.push(`'${removedText}'${j1} ${phrase}이라 제외, '${subjectText}'${j2} 비교`);
  }

  if (!sentences.length && !salient.query_tokens.length && hasQueryName) {
    sentences.push("식별력 있는 부분이 없어 전체로 비교했어요");
  }
  return sentences;
}

function TrademarkImageV2({
  value,
  alt,
  className,
}: {
  value?: string | null;
  alt: string;
  className: string;
}) {
  const [failed, setFailed] = useState(false);
  const src = imageUrl(value);

  if (!src || failed) {
    return (
      <span
        aria-label="상표 이미지 없음"
        role="img"
        className={`${className} flex items-center justify-center bg-low-bg text-sub`}
      >
        <ImageIcon aria-hidden size={22} strokeWidth={1.7} />
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- same-origin BFF image path
    <img
      src={src}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={`${className} bg-white object-contain`}
    />
  );
}

function AxisValues({ axes }: { axes: SearchV2Candidate["axes"] }) {
  const present = AXIS_VALUE_ORDER.filter((key) => axes[key] !== null);
  const missing = AXIS_VALUE_ORDER.filter((key) => axes[key] === null);
  const ordered = [...present, ...missing];

  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="축별 원점수">
      {ordered.map((key) => {
        const value = axes[key];
        return (
          <li
            key={key}
            className={`rounded-full px-2.5 py-1 text-[11px] font-bold tnum ${
              value === null ? "bg-low-bg text-sub" : "bg-blue-bg text-blue-dark"
            }`}
          >
            {AXIS_VALUE_LABEL[key]} {value === null ? "정보 없음" : `${toPercent(value)}%`}
          </li>
        );
      })}
    </ul>
  );
}

function ContributionBars({ risk }: { risk: SearchV2Candidate["risk"] }) {
  const entries = CONTRIBUTION_ORDER.map((key) => ({
    key,
    value: risk.contributions[key] ?? 0,
  }));
  const positive = entries.filter((entry) => entry.value > 0).sort((a, b) => b.value - a.value);
  const negative = entries.filter((entry) => entry.value < 0);
  const positiveSum = positive.reduce((sum, entry) => sum + entry.value, 0);

  if (!positive.length && !negative.length) {
    return <p className="text-[11px] text-sub">근거 축 정보가 없어요</p>;
  }

  return (
    <div>
      <ul className="flex flex-col gap-1.5" aria-label="등급 근거 축(기여도 순)">
        {positive.map((entry) => {
          const width = positiveSum > 0 ? Math.round((entry.value / positiveSum) * 100) : 0;
          return (
            <li key={entry.key} className="grid grid-cols-[86px_minmax(0,1fr)] items-center gap-2">
              <span className="text-[11px] font-semibold text-ink">
                {CONTRIBUTION_LABEL[entry.key]}
              </span>
              {/* 막대 길이 = 근거 가운데 이 축이 차지하는 몫 — 같은 뜻을 글자로도 읽히게 한다 */}
              <span
                role="img"
                aria-label={`근거 가운데 ${width}%`}
                className="relative h-2.5 overflow-hidden rounded-sm bg-low-bg"
              >
                <span
                  className="block h-full bg-blue-dark"
                  style={{ width: `${Math.max(width, 3)}%` }}
                />
              </span>
            </li>
          );
        })}
      </ul>
      {negative.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-[10.5px] font-semibold text-sub">
            위험을 낮춘 요소 {negative.length}개
          </summary>
          <ul className="mt-1.5 flex flex-col gap-1 pl-1">
            {negative.map((entry) => (
              <li key={entry.key} className="text-[10.5px] text-sub">
                {CONTRIBUTION_LABEL[entry.key]} ({entry.value.toFixed(2)})
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function CandidateCard({
  candidate,
  hasQueryName,
  gradePrecision,
  cuts,
}: {
  candidate: SearchV2Candidate;
  hasQueryName: boolean;
  /** meta.grade_precision — "위험" 등급 카드 옆 "검증 데이터 기준 10건 중 N건"(§4-3, 상수 금지). */
  gradePrecision: number;
  /** 이 판단의 등급 하한(thresholdsFor) — 눈금용. */
  cuts: GradeCuts;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const view = GRADE_VIEW[candidate.risk.grade];
  const nameless = isNamelessPattern(candidate.risk.pattern);
  const name = candidate.title ?? "이름 미등록 상표";
  const sentences = buildSalientSentences(candidate.salient, hasQueryName);
  // §4-2: 제외 사유 원문(removed[].reason 그대로)은 툴팁과 "자세히" 토글로
  const reasonTitle = candidate.salient.removed
    .map((item) => `${item.token}: ${item.reason}`)
    .join("\n");
  // §4-8: 업종은 다르지만 표장이 닮은 후보 — "업종 다름" 표시와 설명 한 줄(엔진이 정한 값 그대로)
  const crossGoodsText = crossGoodsLine(candidate);
  // §4-1: 규칙 사유 — 최종 등급과 어긋나지 않는 문장만("업종 다름" 표시가 있으면 업종 상한 줄은 숨김)
  const ruleLines = ruleTriggerLines(
    candidate.risk.rule_triggers,
    candidate.risk.grade,
    crossGoodsText !== null,
  );

  return (
    <li className="border-b border-line last:border-b-0">
      {/* 제목으로 찾아갈 수 있게 후보 이름을 h3 로(화면에는 보이지 않는다 — 카드 전체가 펼치는 버튼이라) */}
      <h3 className="sr-only">{name}</h3>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="w-full px-1 py-3.5 text-left transition-colors hover:bg-bg/70"
        aria-expanded={open}
        aria-controls={detailsId}
      >
        <span className="flex items-start gap-3">
          <span className="relative h-14 w-14 shrink-0 overflow-hidden rounded-sm border border-line">
            <TrademarkImageV2
              value={candidate.image_url}
              alt={`${name} 상표 이미지`}
              className="h-full w-full"
            />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="break-words text-[14px] font-extrabold">{name}</span>
              {candidate.type && (
                <span className="rounded-full bg-low-bg px-2 py-0.5 text-[10px] font-bold text-sub">
                  {candidate.type}
                </span>
              )}
              {candidate.famous_brand && (
                <span
                  data-testid="candidate-famous-brand"
                  className="rounded-full bg-blue-bg px-2 py-0.5 text-[10px] font-bold text-blue-dark"
                >
                  {`유명 상표 · ${candidate.famous_brand}`}
                </span>
              )}
              {crossGoodsText && (
                <span
                  data-testid="candidate-cross-goods"
                  className="rounded-full border border-line bg-card px-2 py-0.5 text-[10px] font-bold text-ink"
                >
                  {CROSS_GOODS_TEXT.badge}
                </span>
              )}
            </span>
            <span className="mt-0.5 block break-words text-[11.5px] text-sub">
              {[
                candidate.applicant,
                candidate.nice_classes.length ? `제 ${candidate.nice_classes.join("·")}류` : null,
              ]
                .filter(Boolean)
                .join(" · ") || "세부 정보 없음"}
            </span>
            <span className="mt-2 block">
              <AxisValues axes={candidate.axes} />
            </span>
            {crossGoodsText && (
              <span
                data-testid="candidate-cross-goods-line"
                className="mt-2 block break-words text-[11.5px] leading-relaxed text-ink"
              >
                {crossGoodsText}
              </span>
            )}
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1">
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${view.pill}`}>
              {candidate.risk.grade}
            </span>
            {candidate.risk.grade === "위험" && !nameless && (
              <span className="tnum text-[10px] text-sub">
                검증 데이터 기준 10건 중 {Math.round(gradePrecision * 10)}건
              </span>
            )}
          </span>
          <ChevronDown
            aria-hidden
            size={18}
            className={`mt-1 shrink-0 text-sub transition-transform ${open ? "rotate-180" : ""}`}
          />
        </span>
      </button>

      {open && (
        <div id={detailsId} className="border-t border-line bg-bg/70 px-4 py-4">
          <div className="grid gap-4 sm:grid-cols-[168px_minmax(0,1fr)]">
            <TrademarkImageV2
              value={candidate.image_url}
              alt={`${name} 선행상표 확대 이미지`}
              className="aspect-square w-full max-w-[168px] rounded-sm border border-line"
            />
            <div className="min-w-0">
              <GradeScale
                cuts={cuts}
                grade={candidate.risk.grade}
                prob={nameless ? null : candidate.risk.prob}
              />
              {nameless && (
                <p className="mt-1.5 text-[10.5px] text-sub" data-testid="nameless-judgment">
                  이름 없이 로고{candidate.axes.x4 !== null ? "·지정상품" : ""}만으로 본 판단이라
                  위험도 %는 보이지 않아요
                </p>
              )}
              <h4 className="mt-3 text-[11px] font-semibold text-sub">등급 근거 축</h4>
              <div className="mt-2">
                <ContributionBars risk={candidate.risk} />
              </div>
              {ruleLines.length > 0 && (
                <ul className="mt-3 flex flex-col gap-1">
                  {ruleLines.map((line) => (
                    <li
                      key={line}
                      className="flex items-start gap-1.5 text-[11px] font-semibold text-review-deep"
                    >
                      <AlertTriangle aria-hidden size={13} className="mt-0.5 shrink-0" />
                      {line}
                    </li>
                  ))}
                </ul>
              )}
              {sentences.length > 0 && (
                <ul className="mt-3 flex flex-col gap-1">
                  {sentences.map((sentence) => (
                    <li
                      key={sentence}
                      title={reasonTitle || undefined}
                      className="text-[11.5px] leading-relaxed text-sub"
                    >
                      {sentence}
                    </li>
                  ))}
                </ul>
              )}
              {candidate.salient.removed.length > 0 && (
                <details className="mt-1.5">
                  <summary className="cursor-pointer text-[10.5px] font-semibold text-sub">
                    제외 사유 자세히
                  </summary>
                  <ul className="mt-1 flex flex-col gap-0.5 pl-1" aria-label="제외 토큰 사유 원문">
                    {candidate.salient.removed.map((item) => (
                      <li key={`${item.side}:${item.token}`} className="text-[10.5px] text-sub">
                        &apos;{item.token}&apos;({SIDE_LABEL[item.side]}) — {item.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {candidate.risk.figure_caveat && (
                <p className="mt-3 rounded-sm bg-low-bg px-2.5 py-1.5 text-[10.5px] font-semibold text-sub">
                  {FIGURE_CAVEAT_TEXT}
                </p>
              )}
              {candidate.goods.codes.length > 0 && (
                <p className="mt-3 text-[11px] text-sub">
                  지정상품 유사군 {candidate.goods.codes.join(", ")}
                  {candidate.goods.jaccard !== null &&
                    ` (겹침 ${toPercent(candidate.goods.jaccard)}%)`}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}

/** 처음 보이는 범위 밖의 "업종은 다르지만 표장이 닮은 상표" — 목록 아래 접힌 칸(계약 v2 §4-8). */
function CrossGoodsMoreSection({
  count,
  candidates,
  hasQueryName,
  meta,
}: {
  count: number;
  candidates: SearchV2Candidate[];
  hasQueryName: boolean;
  meta: SearchV2Response["meta"];
}) {
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const panelId = useId();
  const note = crossGoodsMoreNote(count, candidates.length);

  return (
    <section
      aria-labelledby={headingId}
      data-testid="cross-goods-more"
      className="rounded-lg bg-card p-2"
    >
      <h2 id={headingId}>
        <button
          type="button"
          data-testid="cross-goods-more-toggle"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((current) => !current)}
          className="press flex w-full items-center justify-between gap-2 rounded-md px-2 py-2.5 text-left text-[13px] font-bold text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-dark"
        >
          <span className="min-w-0 break-words">{crossGoodsMoreTitle(count)}</span>
          <ChevronDown
            aria-hidden
            size={18}
            className={`shrink-0 text-sub transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
      </h2>
      <div id={panelId} hidden={!open} data-testid="cross-goods-more-panel">
        {note && (
          <p data-testid="cross-goods-more-note" className="px-2 pb-1 text-[11.5px] text-sub">
            {note}
          </p>
        )}
        <ul>
          {candidates.map((candidate) => (
            <CandidateCard
              key={candidate.id}
              candidate={candidate}
              hasQueryName={hasQueryName}
              gradePrecision={meta.grade_precision}
              cuts={thresholdsFor(meta, candidate.risk.pattern)}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}

export default function ResultViewV2({
  result,
  queryPreview,
  queryHasName,
  queryName,
  onReset,
  onRename,
  onRetypeTo,
  onUseSuggestedName,
  query,
  onAddName,
}: {
  result: SearchV2Response;
  queryPreview: string | null;
  /** 요청에 상표명(name)을 넣었는지 — salient 문장의 "전체로 비교" 폴백 판단에 쓴다. */
  queryHasName: boolean;
  /** 요청에 넣은 상표명 그대로 — 설명적 이름 안내가 "'{이름}'은(는) …"에 쓴다(§4-7). */
  queryName?: string | null;
  onReset: () => void;
  /** "다른 이름으로 다시 확인하기" — 입력을 그대로 둔 채 입력 화면으로 돌아가 이름 칸에 포커스. */
  onRename?: () => void;
  /** "유형 고치기" — type_override 를 채워 입력 화면으로 돌아간다(새 Turnstile 토큰으로 재요청). */
  onRetypeTo?: (type: "문자" | "도형" | "결합") => void;
  /** "상표명으로 넣기" — OCR 이 읽은 글자를 이름 칸에 채워 입력 화면으로 돌아간다. */
  onUseSuggestedName?: (name: string) => void;
  /** 화면이 갖고 있는 입력 상태(이름·로고·업종) — 검색 내용 한 줄에 쓴다. 없으면 그 줄을 그리지 않는다. */
  query?: QuerySummaryInput | null;
  /** 로고만 넣은 검색의 "이름 넣고 다시 확인하기" — 입력 화면으로 돌아가 이름 칸에 포커스(글자가 오면
   *  이름 칸에 채운다). 로고·업종·고친 유형은 유지한다. */
  onAddName?: (name: string | null) => void;
}) {
  const { overall, candidates, meta } = result;
  const view = overall.grade ? GRADE_VIEW[overall.grade] : null;
  // 전체 등급이 이름 없는 판단에서 나왔으면 전체 위험도 %·정밀도 문구를 숨긴다(§4-3·§4-4)
  const overallNameless = isNamelessPattern(overall.pattern);
  // 유명 상표 바닥이 전체 등급을 정했으면(v1.4.7) 위험도 %·눈금·정밀도·등급 설명은 그 등급의 근거가 아니라
  // 그리지 않고 까닭 한 줄만 보인다.
  const famousFloor = overall.famous_floor === true;
  const showPrecision = overall.grade === "위험" && !overallNameless && !famousFloor;
  // 맨 위 안내의 순서(§4-7): ① 유명 상표 배너(강함·약함) ② 설명적 이름 안내 ③ 유명 상표의 "설명적 사용".
  // 배너가 이름 쪽의 강한 일치로 떴으면 설명적 이름 안내와 전체 등급 옆 한 줄은 그리지 않는다.
  const famousLevel = famousBannerLevel(result.famous);
  const famousAfterNotice = famousLevel === FAMOUS_LEVEL_DESCRIPTIVE;
  const famousState = famousBannerState(result.famous);
  // 로고만 넣은 검색 — 이름이 없고 이미지가 있는 질의(이미지가 없으면 visual_status 가 null, §2-1)
  const logoOnly = !queryHasName && overall.visual_status !== null;
  // 로고만 넣은 검색의 상표명 입력 안내(§4-9) — 뜨면 같은 내용의 기존 줄("이미지에서 '…'를 읽었어요"·
  // 주의 목록의 NAME_SUGGESTED)은 그리지 않는다. 사진 안내(PHOTO_QUERY)는 주의 목록에서 맨 위로 옮긴다.
  const logoOnlyKind = logoOnlyNoticeKind(logoOnly, overall.query_type.suggested_name);
  const { photo: photoNotice, rest: caveats } = splitCaveats(overall.caveats, logoOnlyKind !== null);
  const overallHeadingId = useId();
  // 처음 보이는 범위 밖의 "업종은 다르지만 표장이 닮은 상표"(§4-8) — 없으면 칸을 만들지 않는다
  const moreCrossGoods = crossGoodsMore(result);
  const famousBanner = <FamousBanner famous={result.famous} />;
  // "결합-문자요부"·"결합-도형요부" 는 사용자에게는 "결합"으로 보여 주고, 고치기 버튼도 그 기준으로 제외한다.
  const displayType = overall.query_type.type.startsWith("결합") ? "결합" : overall.query_type.type;

  return (
    <div className="flex flex-col gap-4">
      {/* 결과 화면의 제목(§4-10) — 눈에 보이는 제목이 없어 화면에는 보이지 않는 h1 을 둔다. 결과가 나오면
          page.tsx 가 포커스를 여기([data-phase-heading])로 옮긴다. */}
      <h1 data-phase-heading tabIndex={-1} className="sr-only outline-none">
        {ANNOUNCE_TEXT.resultTitle}
      </h1>
      {!famousAfterNotice && famousBanner}
      <DescriptiveNotice
        nameWords={result.name_words}
        candidates={candidates}
        queryName={queryName}
        famousBanner={famousState}
        onRename={onRename}
      />
      {famousAfterNotice && famousBanner}
      {photoNotice && <PhotoNotice text={photoNotice} />}
      {logoOnlyKind && (
        <LogoOnlyNotice
          kind={logoOnlyKind}
          suggestedName={overall.query_type.suggested_name}
          onAddName={onAddName}
        />
      )}
      {query && <QuerySummary query={query} />}
      <section
        aria-labelledby={overallHeadingId}
        className={`rounded-lg border p-5 ${view ? `${view.border} ${view.bg}` : "border-line bg-card"}`}
      >
        <h2 id={overallHeadingId} className="sr-only">
          전체 등급
        </h2>
        <div className="flex items-start gap-4">
          {queryPreview && (
            // eslint-disable-next-line @next/next/no-img-element -- local blob preview
            <img
              src={queryPreview}
              alt="업로드한 로고 미리보기"
              className="h-16 w-16 shrink-0 rounded-md border border-line bg-white object-contain"
            />
          )}
          <div className="min-w-0 flex-1">
            {overall.grade ? (
              <>
                <span className="flex flex-wrap items-center gap-2">
                  <span
                    data-testid="overall-grade"
                    className={`inline-block rounded-full px-3 py-1 text-[13px] font-extrabold ${view!.pill}`}
                  >
                    {overall.grade}
                  </span>
                  {overall.prob !== null && !overallNameless && !famousFloor && (
                    <span
                      data-testid="overall-prob"
                      className={`tnum text-[13px] font-extrabold ${view!.text}`}
                    >
                      위험도 {toPercent(overall.prob)}%
                    </span>
                  )}
                </span>
                {!famousFloor && (
                  <GradeScale
                    cuts={thresholdsFor(meta, overall.pattern)}
                    grade={overall.grade}
                    prob={overallNameless ? null : overall.prob}
                  />
                )}
                {famousFloor ? (
                  <p
                    data-testid="famous-floor-reason"
                    className={`mt-2 text-[13px] font-semibold ${view!.text}`}
                  >
                    {famousFloorReason(result.famous, overall.grade)}
                  </p>
                ) : (
                  <p className={`mt-2 text-[13px] font-semibold ${view!.text}`}>
                    {gradeDescription(overall.grade, logoOnly)}
                  </p>
                )}
                {showsWholeNameLine(result.name_words, candidates, famousState) && (
                  <p data-testid="descriptive-whole-name" className="mt-1 text-[11.5px] text-sub">
                    {NOTICE_TEXT.wholeName}
                  </p>
                )}
                {showsCrossGoodsOverallLine(result) && (
                  <p data-testid="cross-goods-overall" className="mt-1 text-[11.5px] text-sub">
                    {CROSS_GOODS_TEXT.overall}
                  </p>
                )}
                {!queryHasName && (
                  <p data-testid="nameless-guidance" className="mt-1 text-[11.5px] text-sub">
                    {NAMELESS_GUIDANCE}
                  </p>
                )}
                {showPrecision && (
                  <p className="mt-1 text-[11.5px] text-sub">
                    &apos;위험&apos;으로 나온 상표 쌍은 검증 데이터 기준 10건 중{" "}
                    {Math.round(meta.grade_precision * 10)}건이 심결에서 유사로 판단됐어요
                  </p>
                )}
              </>
            ) : (
              <span className="inline-block rounded-full bg-low-bg px-3 py-1 text-[13px] font-extrabold text-sub">
                비교할 후보가 없어요
              </span>
            )}

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-card px-2.5 py-1 text-[11px] font-semibold text-sub">
                유형: {overall.query_type.type}
                {overall.query_type.source === "ocr" && "(이미지에서 판정)"}
              </span>
              {onRetypeTo && (
                <div className="flex gap-1">
                  {(["문자", "도형", "결합"] as const)
                    .filter((type) => type !== displayType)
                    .map((type) => (
                      <button
                        key={type}
                        type="button"
                        onClick={() => onRetypeTo(type)}
                        className="press rounded-full border border-line bg-card px-2.5 py-1 text-[11px] font-semibold text-sub hover:border-blue-dark hover:text-blue-dark"
                      >
                        {retypeLabel(type)}
                      </button>
                    ))}
                </div>
              )}
            </div>

            {overall.visual_status && (
              <p className="mt-2 text-[11px] text-sub">
                시각 유사 상태: {VISUAL_STATUS_VIEW[overall.visual_status].headline}
              </p>
            )}

            {logoOnlyKind === null && overall.query_type.suggested_name && onUseSuggestedName && (
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md bg-card px-3 py-2">
                <span className="text-[11.5px] text-sub">
                  이미지에서 &apos;{overall.query_type.suggested_name}&apos;
                  {josaEulReul(overall.query_type.suggested_name)} 읽었어요
                </span>
                <button
                  type="button"
                  onClick={() => onUseSuggestedName(overall.query_type.suggested_name!)}
                  className="press flex items-center gap-1 rounded-full bg-blue-dark px-3 py-1 text-[11px] font-bold text-white"
                >
                  <Wand2 aria-hidden size={12} />
                  상표명으로 넣기
                </button>
              </div>
            )}

            {caveats.length > 0 && <h2 className="sr-only">주의할 점</h2>}
            {caveats.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1">
                {caveats.map((caveat) => (
                  <li key={caveat} className="text-[11px] leading-relaxed text-sub">
                    <span aria-hidden>· </span>
                    <span>{caveat}</span>
                  </li>
                ))}
              </ul>
            )}
            <p data-testid="reference-note" className="mt-3 text-[10.5px] text-sub">
              {REFERENCE_NOTE}
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="candidates-v2-title" className="rounded-lg bg-card p-2">
        <h2 id="candidates-v2-title" className="sr-only">
          유사 상표 후보
        </h2>
        {candidates.length > 0 ? (
          <ul>
            {candidates.map((candidate) => (
              <CandidateCard
                key={candidate.id}
                candidate={candidate}
                hasQueryName={queryHasName}
                gradePrecision={meta.grade_precision}
                cuts={thresholdsFor(meta, candidate.risk.pattern)}
              />
            ))}
          </ul>
        ) : (
          <p className="p-4 text-[12.5px] text-sub">비교할 후보가 없어요.</p>
        )}
      </section>

      {moreCrossGoods && (
        <CrossGoodsMoreSection
          count={moreCrossGoods.count}
          candidates={moreCrossGoods.candidates}
          hasQueryName={queryHasName}
          meta={meta}
        />
      )}

      <p className="px-1 text-[10.5px] leading-relaxed text-sub">
        비교 대상: 등록상표 {result.dataset_info.총_상표수.toLocaleString()}건 ·{" "}
        {result.dataset_info.데이터_기준} · 모델 {meta.model_version} · 결과는 참고 정보이며 법적
        판단이 아니에요.
      </p>

      <button
        type="button"
        onClick={onReset}
        className="press flex items-center justify-center gap-1.5 rounded-md border border-line bg-card py-3 text-[13px] font-bold text-sub"
      >
        <RotateCcw aria-hidden size={14} />
        다른 로고 비교하기
      </button>
    </div>
  );
}
