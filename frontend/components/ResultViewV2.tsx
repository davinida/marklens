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
import type { SearchV2Candidate, SearchV2Response } from "@/lib/contracts";
// v1 결과 화면의 시각 4상태 문구(API 계약 v2 §4-5: v1 과 같은 문구로 보여 준다)
import { GRADE_VIEW as VISUAL_STATUS_VIEW } from "@/components/ResultView";

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
  }
> = {
  안전: {
    text: "text-low",
    border: "border-low",
    bg: "bg-low-bg",
    pill: "bg-low text-white",
    bar: "bg-low",
    description: "비교 표본에서 가까운 후보를 찾지 못했습니다 — 안전 판정이 아닙니다",
  },
  주의: {
    text: "text-warn-deep",
    border: "border-warn",
    bg: "bg-warn-bg",
    pill: "bg-warn-deep text-white",
    bar: "bg-warn",
    description: "일부 축이 비슷한 후보가 있습니다",
  },
  "검토 권장": {
    text: "text-review-deep",
    border: "border-review",
    bg: "bg-review-bg",
    pill: "bg-review-deep text-white",
    bar: "bg-review",
    description: "비슷한 선행 상표가 있을 수 있습니다. 전문가 검토를 권장합니다",
  },
  위험: {
    text: "text-caution-deep",
    border: "border-caution",
    bg: "bg-caution-bg",
    pill: "bg-caution-deep text-white",
    bar: "bg-caution",
    description: "여러 축이 비슷한 선행 상표가 있습니다",
  },
};

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

const RULE_TRIGGER_TEXT: Record<string, string> = {
  standalone_x1: "호칭이 거의 같아 검토 권장으로 올렸습니다",
  standalone_x2_text: "철자가 매우 비슷해 검토 권장으로 올렸습니다",
  standalone_x3: "뜻이 매우 비슷해 검토 권장으로 올렸습니다",
  figure_x2_img: "도형이 매우 비슷해 검토 권장으로 올렸습니다(검증 데이터 부족, 참고용)",
};

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

// 종성(받침) 유무로 조사를 고른다. 한글 음절이 아니면(라틴 문자 등) 받침 없는 것으로 본다.
function hasBatchim(text: string): boolean {
  const last = text.trim().slice(-1);
  const code = last.charCodeAt(0);
  if (code < 0xac00 || code > 0xd7a3) return false;
  return (code - 0xac00) % 28 !== 0;
}
function josaEunNeun(text: string): "은" | "는" {
  return hasBatchim(text) ? "은" : "는";
}
function josaEuroRo(text: string): "으로" | "로" {
  if (!hasBatchim(text)) return "로";
  const code = text.trim().slice(-1).charCodeAt(0);
  const finalConsonant = (code - 0xac00) % 28;
  return finalConsonant === 8 ? "로" : "으로"; // 8 = ㄹ 받침
}

function toPercent(value: number): number {
  return Math.round(Math.max(0, Math.min(1, value)) * 100);
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
      sentences.push(`'${removedText}'${j1} ${phrase}이라 제외했습니다`);
      continue;
    }
    const subjectText = subjectTokens.join("·");
    const j2 = josaEuroRo(subjectText);
    sentences.push(`'${removedText}'${j1} ${phrase}이라 제외, '${subjectText}'${j2} 비교`);
  }

  if (!sentences.length && !salient.query_tokens.length && hasQueryName) {
    sentences.push("식별력 있는 부분이 없어 전체로 비교했습니다");
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
    return <p className="text-[11px] text-sub">근거 축 정보가 없습니다</p>;
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
              <span className="relative h-2.5 overflow-hidden rounded-sm bg-low-bg">
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
}: {
  candidate: SearchV2Candidate;
  hasQueryName: boolean;
  /** meta.grade_precision — "위험" 등급 카드 옆 "검증 데이터 기준 10건 중 N건"(§4-3, 상수 금지). */
  gradePrecision: number;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const view = GRADE_VIEW[candidate.risk.grade];
  const name = candidate.title ?? "이름 미등록 상표";
  const sentences = buildSalientSentences(candidate.salient, hasQueryName);
  // §4-2: 제외 사유 원문(removed[].reason 그대로)은 툴팁과 "자세히" 토글로
  const reasonTitle = candidate.salient.removed
    .map((item) => `${item.token}: ${item.reason}`)
    .join("\n");

  return (
    <li className="border-b border-line last:border-b-0">
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
          </span>
          <span className="flex shrink-0 flex-col items-end gap-1">
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-extrabold ${view.pill}`}>
              {candidate.risk.grade}
            </span>
            {candidate.risk.grade === "위험" && (
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
              <h4 className="text-[11px] font-semibold text-sub">등급 근거 축</h4>
              <div className="mt-2">
                <ContributionBars risk={candidate.risk} />
              </div>
              {candidate.risk.rule_triggers.length > 0 && (
                <ul className="mt-3 flex flex-col gap-1">
                  {candidate.risk.rule_triggers.map((trigger) => (
                    <li
                      key={trigger}
                      className="flex items-start gap-1.5 text-[11px] font-semibold text-review-deep"
                    >
                      <AlertTriangle aria-hidden size={13} className="mt-0.5 shrink-0" />
                      {RULE_TRIGGER_TEXT[trigger] ?? trigger}
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
                  도형 유사는 검증 데이터가 적어 참고용
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

export default function ResultViewV2({
  result,
  queryPreview,
  queryHasName,
  onReset,
  onRetypeTo,
  onUseSuggestedName,
}: {
  result: SearchV2Response;
  queryPreview: string | null;
  /** 요청에 상표명(name)을 넣었는지 — salient 문장의 "전체로 비교" 폴백 판단에 쓴다. */
  queryHasName: boolean;
  onReset: () => void;
  /** "유형 고치기" — type_override 를 채워 입력 화면으로 돌아간다(새 Turnstile 토큰으로 재요청). */
  onRetypeTo?: (type: "문자" | "도형" | "결합") => void;
  /** "상표명으로 넣기" — OCR 이 읽은 글자를 이름 칸에 채워 입력 화면으로 돌아간다. */
  onUseSuggestedName?: (name: string) => void;
}) {
  const { overall, candidates, meta } = result;
  const view = overall.grade ? GRADE_VIEW[overall.grade] : null;
  const showPrecision = overall.grade === "위험";
  // "결합-문자요부"·"결합-도형요부" 는 사용자에게는 "결합"으로 보여 주고, 고치기 버튼도 그 기준으로 제외한다.
  const displayType = overall.query_type.type.startsWith("결합") ? "결합" : overall.query_type.type;

  return (
    <div className="flex flex-col gap-4">
      <section className={`rounded-lg border p-5 ${view ? `${view.border} ${view.bg}` : "border-line bg-card"}`}>
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
                  {overall.prob !== null && (
                    <span
                      data-testid="overall-prob"
                      className={`tnum text-[13px] font-extrabold ${view!.text}`}
                    >
                      위험도 {toPercent(overall.prob)}%
                    </span>
                  )}
                </span>
                <p className={`mt-2 text-[13px] font-semibold ${view!.text}`}>{view!.description}</p>
                {showPrecision && (
                  <p className="mt-1 text-[11.5px] text-sub">
                    &apos;위험&apos;으로 분류된 상표 쌍은 검증 데이터 기준 10건 중{" "}
                    {Math.round(meta.grade_precision * 10)}건이 심결에서 유사로 판단됐습니다
                  </p>
                )}
              </>
            ) : (
              <span className="inline-block rounded-full bg-low-bg px-3 py-1 text-[13px] font-extrabold text-sub">
                비교할 후보가 없습니다
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
                        {type}로 고치기
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

            {overall.query_type.suggested_name && onUseSuggestedName && (
              <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md bg-card px-3 py-2">
                <span className="text-[11.5px] text-sub">
                  이미지에서 &apos;{overall.query_type.suggested_name}&apos;를 읽었습니다
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

            {overall.caveats.length > 0 && (
              <ul className="mt-3 flex flex-col gap-1">
                {overall.caveats.map((caveat) => (
                  <li key={caveat} className="text-[11px] leading-relaxed text-sub">
                    <span aria-hidden>· </span>
                    <span>{caveat}</span>
                  </li>
                ))}
              </ul>
            )}
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
              />
            ))}
          </ul>
        ) : (
          <p className="p-4 text-[12.5px] text-sub">비교할 후보가 없습니다.</p>
        )}
      </section>

      <p className="px-1 text-[10.5px] leading-relaxed text-sub">
        비교 대상: 등록상표 {result.dataset_info.총_상표수.toLocaleString()}건 ·{" "}
        {result.dataset_info.데이터_기준} · 모델 {meta.model_version} · 결과는 참고 정보이며 법적
        판단이 아닙니다.
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
