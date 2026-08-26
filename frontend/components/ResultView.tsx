"use client";

import { useId, useState } from "react";
import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  CircleDashed,
  CircleGauge,
  ImageIcon,
  Layers3,
  MinusCircle,
  RotateCcw,
  Scale,
  Tags,
} from "lucide-react";
import NameCheckPanel from "@/components/NameCheckPanel";
import { imageUrl } from "@/lib/api";
import type {
  GradeCode,
  SearchMatch,
  SearchResponse,
  StatusCode,
} from "@/lib/api";
import type { NameCheckResult } from "@/lib/contracts";

const GRADE_VIEW: Record<
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

const LEGACY_STATUS: Record<GradeCode, StatusCode> = {
  CAUTION: "STRONG_MATCH",
  REVIEW: "POSSIBLE_MATCH",
  LOW: "WEAK_MATCH",
};

function clampSimilarity(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export function similarityPercentage(value: number): number {
  // Flooring at one decimal keeps a raw score below a threshold from visually
  // crossing it through rounding (for example 0.7499 must not display as 75%).
  return Math.floor(clampSimilarity(value) * 1000) / 10;
}

// 색 구간 경계값의 단일 소스는 백엔드 응답(grade.thresholds)이다. 아래 폴백은
// 이 값을 아직 보내지 않는 구버전 백엔드 응답에서만 쓴다(visual-v2와 동일 값).
export interface SimThresholds {
  strong: number;
  possible: number;
  weak: number;
}

export const FALLBACK_THRESHOLDS: SimThresholds = {
  strong: 0.75,
  possible: 0.55,
  weak: 0.45,
};

export function resolveThresholds(
  thresholds: Record<string, number> | undefined,
): SimThresholds | null {
  const strong = thresholds?.strong_match;
  const possible = thresholds?.possible_match;
  const weak = thresholds?.weak_match;
  if (
    typeof strong === "number" &&
    typeof possible === "number" &&
    typeof weak === "number" &&
    weak < possible &&
    possible < strong
  ) {
    return { strong, possible, weak };
  }
  return null;
}

function simTone(similarity: number, t: SimThresholds): string {
  if (similarity >= t.strong) return "text-caution-deep";
  if (similarity >= t.possible) return "text-review-deep";
  return "text-blue-dark";
}

function simBar(similarity: number, t: SimThresholds): string {
  if (similarity >= t.strong) return "bg-caution";
  if (similarity >= t.possible) return "bg-review";
  if (similarity >= t.weak) return "bg-low";
  return "bg-blue-dark";
}

function matchName(match: SearchMatch): string {
  return (
    match.trademark?.상표한글명 ||
    match.trademark?.상표영문명 ||
    match.trademark?.출원번호 ||
    "이름 미등록 상표"
  );
}

function TrademarkImage({
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

function Info({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="min-w-0 border-t border-line py-2.5 first:border-t-0">
      <dt className="text-[11px] font-semibold text-sub">{label}</dt>
      <dd className="mt-0.5 break-words text-[12.5px] font-semibold text-ink tnum">
        {value}
      </dd>
    </div>
  );
}

function MatchRow({
  match,
  thresholds,
}: {
  match: SearchMatch;
  thresholds: SimThresholds;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const trademark = match.trademark;
  const score = similarityPercentage(match.similarity);
  const name = matchName(match);

  return (
    <li id={`candidate-${match.rank}`} className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="w-full px-1 py-3.5 text-left transition-colors hover:bg-bg/70"
        aria-expanded={open}
        aria-controls={detailsId}
        title={`${name} 상세 ${open ? "접기" : "보기"}`}
      >
        <span className="flex items-center gap-3">
          <span className="relative h-14 w-14 shrink-0 overflow-hidden rounded-sm border border-line">
            <TrademarkImage
              value={match.이미지URL}
              alt={`${name} 상표 이미지`}
              className="h-full w-full"
            />
            <span className="absolute left-0 top-0 bg-ink/85 px-1.5 py-0.5 text-[9px] font-bold text-white tnum">
              {match.rank}
            </span>
          </span>
          <span className="min-w-0 flex-1">
            <span className="block break-words text-[14px] font-extrabold">{name}</span>
            <span className="mt-0.5 block break-words text-[11.5px] text-sub">
              {trademark
                ? [
                    trademark.출원인,
                    trademark.류.length ? `제 ${trademark.류.join("·")}류` : null,
                  ]
                    .filter(Boolean)
                    .join(" · ") || "세부 정보 없음"
                : "상표 상세 정보가 연결되지 않았어요"}
            </span>
          </span>
          <span className={`shrink-0 text-right ${simTone(match.similarity, thresholds)}`}>
            <span className="block text-[18px] font-extrabold tnum">{score}%</span>
            <span className="block text-[9.5px] font-semibold">시각 유사도</span>
          </span>
          <ChevronDown
            aria-hidden
            size={18}
            className={`shrink-0 text-sub transition-transform ${open ? "rotate-180" : ""}`}
          />
        </span>
        <span className="mt-2.5 block h-1.5 overflow-hidden rounded-sm bg-low-bg">
          <span
            className={`block h-full ${simBar(match.similarity, thresholds)}`}
            style={{ width: `${score}%` }}
          />
        </span>
      </button>

      {open && (
        <div id={detailsId} className="border-t border-line bg-bg/70 px-4 py-4">
          <div className="grid gap-4 sm:grid-cols-[168px_minmax(0,1fr)]">
            <TrademarkImage
              value={match.이미지URL}
              alt={`${name} 선행상표 확대 이미지`}
              className="aspect-square w-full max-w-[168px] rounded-sm border border-line"
            />
            <dl className="grid min-w-0 grid-cols-1 gap-x-5 sm:grid-cols-2">
              <Info
                label="유사도 원점수"
                value={`${match.similarity.toFixed(4)} (${score}%)`}
              />
              <Info label="검색 순위" value={`${match.rank}위`} />
              <Info label="한글 상표명" value={trademark?.상표한글명 ?? null} />
              <Info label="영문 상표명" value={trademark?.상표영문명 ?? null} />
              <Info label="출원번호" value={trademark?.출원번호 ?? null} />
              <Info label="등록번호" value={trademark?.등록번호 ?? null} />
              <Info label="출원인" value={trademark?.출원인 ?? null} />
              <Info label="최종 권리자" value={trademark?.최종권리자 ?? null} />
              <Info label="상표 구분" value={trademark?.상표구분 ?? null} />
              <Info
                label="상품류"
                value={trademark?.류.length ? `제 ${trademark.류.join("·")}류` : null}
              />
              <Info
                label="유사군 코드"
                value={trademark?.유사군.join(", ") || null}
              />
              <Info
                label="비엔나 코드"
                value={trademark?.비엔나코드.join(", ") || null}
              />
              <Info label="출원일자" value={trademark?.출원일자 ?? null} />
              <Info label="등록일자" value={trademark?.등록일자 ?? null} />
            </dl>
          </div>
        </div>
      )}
    </li>
  );
}

function ScoreScale({
  value,
  thresholdVersion,
  thresholds,
  thresholdsFromPayload,
}: {
  value: number;
  thresholdVersion?: string;
  thresholds: SimThresholds;
  thresholdsFromPayload: boolean;
}) {
  const score = similarityPercentage(value);
  // 응답이 경계값을 실어 보내면 그대로 띠를 그린다. 구버전 응답은 폴백 값이
  // 유효한 버전(visual-v2-uncalibrated)일 때만 띠를 그리고, 아니면 중립 바.
  const knownThresholds =
    thresholdsFromPayload || thresholdVersion === "visual-v2-uncalibrated";
  const thresholdsId = useId();
  const weakPct = Math.round(thresholds.weak * 100);
  const possiblePct = Math.round(thresholds.possible * 100);
  const strongPct = Math.round(thresholds.strong * 100);

  return (
    <div>
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold text-sub">최고 시각 유사도</p>
          <p className={`mt-0.5 text-[28px] font-extrabold tnum ${simTone(value, thresholds)}`}>
            {score}%
          </p>
        </div>
        <p className="max-w-[210px] text-right text-[10.5px] leading-relaxed text-sub">
          이미지 특징 벡터의 코사인 유사도이며 등록 가능성 확률이 아니에요.
        </p>
      </div>
      <div
        role="meter"
        aria-label="최고 시각 유사도"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={score}
        aria-describedby={knownThresholds ? thresholdsId : undefined}
        className="relative mt-3 pt-3"
      >
        <span
          aria-hidden
          className="absolute top-0 h-4 w-0.5 -translate-x-1/2 bg-ink"
          style={{ left: `${Math.max(1, Math.min(99, score))}%` }}
        />
        <div className="flex h-3 overflow-hidden rounded-sm">
          {knownThresholds ? (
            <>
              <span className="bg-blue/45" style={{ width: `${weakPct}%` }} />
              <span className="bg-low" style={{ width: `${possiblePct - weakPct}%` }} />
              <span className="bg-review" style={{ width: `${strongPct - possiblePct}%` }} />
              <span className="bg-caution" style={{ width: `${100 - strongPct}%` }} />
            </>
          ) : (
            <span className="w-full bg-blue/55" />
          )}
        </div>
      </div>
      {knownThresholds && (
        <>
          <div aria-hidden className="relative mt-1.5 h-3 text-[9px] font-semibold text-sub tnum">
            <span className="absolute left-0">0</span>
            <span className="absolute -translate-x-1/2" style={{ left: `${weakPct}%` }}>
              {weakPct}
            </span>
            <span className="absolute -translate-x-1/2" style={{ left: `${possiblePct}%` }}>
              {possiblePct}
            </span>
            <span className="absolute -translate-x-1/2" style={{ left: `${strongPct}%` }}>
              {strongPct}
            </span>
            <span className="absolute right-0">100</span>
          </div>
          <p id={thresholdsId} className="sr-only">
            점수 구간은 {weakPct} 미만, {weakPct} 이상 {possiblePct} 미만, {possiblePct} 이상{" "}
            {strongPct} 미만, {strongPct} 이상입니다.
          </p>
        </>
      )}
    </div>
  );
}

function EvidenceMetric({
  icon,
  label,
  value,
  note,
  fill,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
  fill: number;
}) {
  return (
    <div className="rounded-md border border-line bg-card p-3.5">
      <div className="flex items-start justify-between gap-3">
        <span className="flex h-7 w-7 items-center justify-center rounded-sm bg-blue-bg text-blue-dark">
          {icon}
        </span>
        <strong className="text-[17px] font-extrabold text-ink tnum">{value}</strong>
      </div>
      <p className="mt-2 text-[11.5px] font-bold text-ink">{label}</p>
      <div className="mt-2 h-1.5 overflow-hidden rounded-sm bg-low-bg">
        <span
          className="block h-full bg-blue-dark"
          style={{ width: `${Math.max(0, Math.min(100, fill))}%` }}
        />
      </div>
      <p className="mt-2 text-[10.5px] leading-relaxed text-sub">{note}</p>
    </div>
  );
}

function MatchDistribution({
  matches,
  thresholds,
}: {
  matches: SearchMatch[];
  thresholds: SimThresholds;
}) {
  const visible = matches.slice(0, 8);
  if (!visible.length) return null;

  return (
    <div className="mt-5 border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-[12px] font-extrabold text-ink">후보 점수 분포</h3>
        <span className="text-[10.5px] text-sub">상위 {visible.length}건</span>
      </div>
      <ul className="mt-3 grid min-h-[152px] content-start gap-2.5">
        {visible.map((match) => {
          const score = similarityPercentage(match.similarity);
          return (
            <li key={`distribution-${match.rank}`} className="grid grid-cols-[24px_minmax(0,1fr)_38px] items-center gap-2">
              <span className="text-[10px] font-bold text-sub tnum">#{match.rank}</span>
              <span className="relative h-5 overflow-hidden rounded-sm bg-low-bg">
                <span
                  className={`block h-full ${simBar(match.similarity, thresholds)}`}
                  style={{ width: `${score}%` }}
                />
                <span className="absolute inset-0 truncate px-2 text-[9.5px] font-semibold leading-5 text-ink mix-blend-multiply">
                  {matchName(match)}
                </span>
              </span>
              <span className="text-right text-[10.5px] font-bold text-ink tnum">
                {score}%
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function AnalysisScope({ nameCheck }: { nameCheck?: NameCheckResult | null }) {
  const items = [
    {
      label: "외관",
      state: "분석됨",
      detail: "이미지 특징 유사도",
      kind: "complete" as const,
    },
    {
      label: "동일 명칭",
      state: nameCheck
        ? nameCheck.complete === true
          ? "별도 조회됨"
          : "일부 조회됨"
        : "미확인",
      detail: nameCheck ? "KIPRIS 명칭 검색" : "이름 확인 미실행",
      kind:
        nameCheck?.complete === true
          ? ("complete" as const)
          : nameCheck
            ? ("partial" as const)
            : ("missing" as const),
    },
    {
      label: "호칭·관념",
      state: "미분석",
      detail: "발음·의미 비교 제외",
      kind: "missing" as const,
    },
    {
      label: "상품 견련성",
      state: "미분석",
      detail: "지정상품 충돌 비교 제외",
      kind: "missing" as const,
    },
  ];

  return (
    <div className="mt-5 border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-[12px] font-extrabold text-ink">분석 범위</h3>
        <span className="text-[10.5px] text-sub">4개 판단 축</span>
      </div>
      <div className="mt-3 grid gap-px border border-line bg-line sm:grid-cols-2">
        {items.map((item) => (
          <div key={item.label} className="flex min-w-0 items-start gap-2.5 bg-card p-3">
            {item.kind === "complete" ? (
              <CheckCircle2
                aria-hidden
                size={16}
                className="mt-0.5 shrink-0 text-safe-deep"
              />
            ) : item.kind === "partial" ? (
              <CircleDashed
                aria-hidden
                size={16}
                className="mt-0.5 shrink-0 text-review-deep"
              />
            ) : (
              <MinusCircle
                aria-hidden
                size={16}
                className="mt-0.5 shrink-0 text-sub"
              />
            )}
            <div className="min-w-0">
              <p className="flex flex-wrap items-baseline gap-x-2 text-[11.5px]">
                <strong className="font-extrabold text-ink">{item.label}</strong>
                <span
                  className={`font-bold ${
                    item.kind === "complete"
                      ? "text-safe-deep"
                      : item.kind === "partial"
                        ? "text-review-deep"
                        : "text-sub"
                  }`}
                >
                  {item.state}
                </span>
              </p>
              <p className="mt-0.5 text-[10.5px] leading-relaxed text-sub">{item.detail}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VisualComparison({
  queryPreview,
  topMatch,
  thresholds,
}: {
  queryPreview: string | null;
  thresholds: SimThresholds;
  topMatch: SearchMatch | undefined;
}) {
  const topName = topMatch ? matchName(topMatch) : "비교 후보 없음";
  const score = topMatch ? similarityPercentage(topMatch.similarity) : 0;

  return (
    <section aria-labelledby="comparison-title" className="border-y border-line bg-card px-5 py-5 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-[10.5px] font-bold text-blue-dark">TOP 1 VISUAL MATCH</p>
          <h2 id="comparison-title" className="mt-0.5 text-[16px] font-extrabold">
            로고 나란히 비교
          </h2>
        </div>
        <span className={`text-[24px] font-extrabold tnum ${topMatch ? simTone(topMatch.similarity, thresholds) : "text-sub"}`}>
          {score}%
        </span>
      </div>
      <div className="mt-4 grid grid-cols-[minmax(0,1fr)_42px_minmax(0,1fr)] items-center gap-2 sm:gap-4">
        <figure className="min-w-0 text-center">
          {queryPreview ? (
            // eslint-disable-next-line @next/next/no-img-element -- local object URL
            <img
              src={queryPreview}
              alt="검색한 내 로고"
              className="mx-auto aspect-square w-full max-w-[180px] rounded-sm border border-line bg-white object-contain"
            />
          ) : (
            <span className="mx-auto flex aspect-square w-full max-w-[180px] items-center justify-center rounded-sm border border-line bg-low-bg text-sub">
              <ImageIcon aria-hidden size={26} />
            </span>
          )}
          <figcaption className="mt-2 truncate text-[11px] font-bold text-sub">내 로고</figcaption>
        </figure>
        <div className="text-center">
          <span className="block h-px w-full bg-line" />
          <span className="mt-1 block text-[9px] font-bold text-sub">VS</span>
        </div>
        <figure className="min-w-0 text-center">
          <TrademarkImage
            value={topMatch?.이미지URL}
            alt={`${topName} 상표 이미지`}
            className="mx-auto aspect-square w-full max-w-[180px] rounded-sm border border-line"
          />
          <figcaption className="mt-2 truncate text-[11px] font-bold text-sub">
            {topName}
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

export default function ResultView({
  result,
  queryPreview,
  nameCheck,
  onReset,
}: {
  result: SearchResponse;
  queryPreview: string | null;
  nameCheck?: NameCheckResult | null;
  onReset: () => void;
}) {
  const grade = result.grade;
  const statusCode = grade.status_code ?? LEGACY_STATUS[grade.grade_code];
  const statusName = grade.status_name ?? grade.grade_name;
  const view = GRADE_VIEW[statusCode];
  const payloadThresholds = resolveThresholds(grade.thresholds);
  const thresholds = payloadThresholds ?? FALLBACK_THRESHOLDS;
  const dataset = result.dataset_info;
  const topMatch = result.matches[0];
  const topScore = similarityPercentage(grade.top1_similarity);
  const gapAPoints = Math.max(0, grade.separability_a * 100);
  const gapBPoints = Math.max(0, grade.separability_b * 100);
  const nameIndicator = nameCheck
    ? nameCheck.exactRegisteredCount > 0
      ? `동일 명칭 등록상표 ${nameCheck.complete === true ? "" : "최소 "}${nameCheck.exactRegisteredCount}건 확인`
      : nameCheck.complete === true
        ? "동일 명칭 등록상표 미확인"
        : "동일 명칭 등록상표 검색 일부 확인"
    : null;
  const nameIndicatorTone = nameCheck
    ? nameCheck.exactRegisteredCount > 0
      ? "bg-caution-deep text-white"
      : nameCheck.complete === true
        ? "bg-safe-bg text-safe-deep"
        : "bg-review-bg text-review-deep"
    : "";

  return (
    <div className="flex flex-col gap-4">
      <section
        aria-labelledby="result-title"
        className={`rise border-l-4 px-5 py-5 sm:px-6 ${view.border} ${view.bg}`}
      >
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
          <div className="flex min-w-0 gap-3.5">
            <span
              aria-hidden
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/80 text-[20px] font-extrabold ${view.text}`}
            >
              {view.mark}
            </span>
            <div className="min-w-0">
              <h1
                id="result-title"
                data-phase-heading
                tabIndex={-1}
                className={`text-[22px] font-extrabold leading-snug outline-none ${view.text}`}
              >
                {view.headline}
              </h1>
              <p className="mt-1.5 max-w-[680px] text-[13px] leading-relaxed text-sub">
                {grade.message}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2 sm:justify-end">
            <span className={`rounded-full px-3 py-1 text-[11px] font-bold ${view.pill}`}>
              {statusName}
            </span>
            <span className="rounded-full bg-white/85 px-3 py-1 text-[11px] font-bold text-sub tnum">
              최고 {topScore}%
            </span>
            {nameIndicator && (
              <span
                title="KIPRIS 동일 명칭 별도 검색 결과"
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-bold ${nameIndicatorTone}`}
              >
                <Tags aria-hidden size={13} />
                {nameIndicator}
              </span>
            )}
          </div>
        </div>

        {(grade.warnings.length > 0 || grade.uncertain) && (
          <div className="mt-4 grid gap-2 border-t border-current/10 pt-3 sm:grid-cols-2">
            {grade.warnings.map((warning) => (
              <p key={warning} className="text-[11.5px] font-semibold leading-relaxed text-review-deep">
                {warning}
              </p>
            ))}
            {grade.uncertain && grade.warnings.length === 0 && (
              <p className="text-[11.5px] font-semibold leading-relaxed text-review-deep">
                후보 점수가 서로 가까워 대표 후보의 순위가 불확실해요.
              </p>
            )}
          </div>
        )}
      </section>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
        <div className="grid min-w-0 gap-4">
          <VisualComparison
            queryPreview={queryPreview}
            topMatch={topMatch}
            thresholds={thresholds}
          />

          <section aria-labelledby="evidence-title" className="border-y border-line bg-card px-5 py-5 sm:px-6">
            <div className="flex items-center gap-2">
              <BarChart3 aria-hidden size={18} className="text-blue-dark" />
              <h2 id="evidence-title" className="text-[16px] font-extrabold">
                분석 근거 대시보드
              </h2>
            </div>
            <p className="mt-1 text-[11.5px] leading-relaxed text-sub">
              최고 점수, 후보 간 격차, 전체 후보 분포를 함께 보면 단일 점수보다 검색 결과를
              더 정확히 해석할 수 있어요.
            </p>

            <div className="mt-5">
              <ScoreScale
                value={grade.top1_similarity}
                thresholdVersion={grade.threshold_version}
                thresholds={thresholds}
                thresholdsFromPayload={payloadThresholds !== null}
              />
            </div>

            <div className="mt-5 grid gap-2.5 sm:grid-cols-3">
              <EvidenceMetric
                icon={<CircleGauge aria-hidden size={16} />}
                label="최고 후보 점수"
                value={`${topScore}%`}
                fill={topScore}
                note="가장 가까운 이미지 특징 후보의 원점수"
              />
              <EvidenceMetric
                icon={<Scale aria-hidden size={16} />}
                label="1·2위 점수 차"
                value={`${gapAPoints.toFixed(1)}p`}
                fill={gapAPoints}
                note="작을수록 여러 후보가 비슷하게 가까움"
              />
              <EvidenceMetric
                icon={<Layers3 aria-hidden size={16} />}
                label="1위·평균 점수 차"
                value={`${gapBPoints.toFixed(1)}p`}
                fill={gapBPoints}
                note="1위가 판정 후보 평균보다 앞선 정도"
              />
            </div>

            <MatchDistribution matches={result.matches} thresholds={thresholds} />
            <AnalysisScope nameCheck={nameCheck} />
          </section>
        </div>

        <div className="grid min-w-0 gap-4">
          {nameCheck && (
            <section
              data-name-evidence
              aria-labelledby="name-evidence-title"
              className="border-y border-line bg-card px-5 py-5"
            >
              <h2 id="name-evidence-title" className="sr-only">명칭 검색 분석</h2>
              <NameCheckPanel result={nameCheck} />
            </section>
          )}

          <section
            data-visual-candidates
            aria-labelledby="matches-title"
            className="border-y border-line bg-card px-5 py-5"
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 id="matches-title" className="text-[16px] font-extrabold">
                  시각 유사 후보
                </h2>
                <p className="mt-0.5 text-[11px] text-sub">
                  후보를 누르면 로고와 KIPRIS 정보를 자세히 볼 수 있어요.
                </p>
              </div>
              <span className="shrink-0 text-[12px] font-bold text-blue-dark tnum">
                {result.top_k_returned}건
              </span>
            </div>
            {result.matches.length > 0 ? (
              <ul className="mt-3 border-t border-line">
                {result.matches.map((match) => (
                  <MatchRow
                    key={`${match.rank}-${match.이미지파일 ?? "none"}`}
                    match={match}
                    thresholds={thresholds}
                  />
                ))}
              </ul>
            ) : (
              <p className="mt-4 border-y border-line py-6 text-center text-[13px] text-sub">
                표시할 유사 상표가 없어요.
              </p>
            )}
          </section>

        </div>
      </div>

      <details className="group border-y border-line bg-card px-5 py-4 sm:px-6">
        <summary className="flex cursor-pointer list-none items-center justify-between text-[14px] font-extrabold [&::-webkit-details-marker]:hidden">
          데이터 범위와 판정 기준
          <ChevronDown
            aria-hidden
            size={18}
            className="text-sub transition-transform group-open:rotate-180"
          />
        </summary>
        <dl className="mt-4 grid grid-cols-2 gap-x-5 text-[12px] sm:grid-cols-4">
          <Info label="비교 축" value="이미지 특징 유사도" />
          <Info label="인덱스 크기" value={`${result.index_size}건`} />
          <Info
            label="요청/반환"
            value={`${result.top_k_requested} / ${result.top_k_returned}`}
          />
          <Info
            label="판정 후보 수"
            value={
              grade.scored_candidate_count !== undefined
                ? `${grade.scored_candidate_count}건`
                : null
            }
          />
          <Info label="임계값 버전" value={grade.threshold_version ?? null} />
          <Info label="데이터 기준" value={dataset.데이터_기준} />
          <Info label="출원일자 범위" value={dataset.출원일자_범위} />
          <Info label="생성일자" value={dataset.생성일자} />
        </dl>
        <p className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-sub">
          {grade.calibrated === false && "교정 전 연구용 임계값을 사용했어요. "}
          실제 등록 가능성은 표장, 명칭, 지정상품, 권리 상태를 함께 검토해야 하며 이 결과는
          법률 의견이 아니에요.
        </p>
      </details>

      <div className="pt-1">
        <button
          type="button"
          onClick={onReset}
          className="press flex w-full items-center justify-center gap-2 rounded-md bg-blue-dark py-4 text-[15px] font-bold text-white hover:bg-[#174ea6]"
        >
          <RotateCcw aria-hidden size={17} />
          다른 로고 비교하기
        </button>
        <p className="mt-3 text-center text-[10.5px] leading-relaxed text-sub tnum">
          총 {dataset.총_상표수}건 기준 · 법적 판단이 아닌 선행 후보 탐색 결과예요.
        </p>
      </div>
    </div>
  );
}
