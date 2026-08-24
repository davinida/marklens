"use client";

import { useId, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Database,
  ExternalLink,
  ImageIcon,
  ListPlus,
} from "lucide-react";
import { imageUrl } from "@/lib/api";
import type {
  NameCheckCandidate,
  NameCheckResult,
} from "@/lib/contracts";

function statusTone(status: string): string {
  if (status.includes("등록")) return "bg-caution";
  if (status.includes("출원") || status.includes("공고")) return "bg-review";
  if (status.includes("소멸") || status.includes("거절")) return "bg-low";
  return "bg-blue";
}

function CandidateImage({ candidate }: { candidate: NameCheckCandidate }) {
  const [failed, setFailed] = useState(false);
  const src = imageUrl(candidate.localImageUrl);

  if (!src || failed) {
    return (
      <span
        role="img"
        aria-label={`${candidate.name} 상표 이미지 없음`}
        className="flex h-full w-full items-center justify-center bg-low-bg text-sub"
      >
        <ImageIcon aria-hidden size={20} strokeWidth={1.8} />
      </span>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- same-origin BFF image path
    <img
      src={src}
      alt={`${candidate.name} 선행상표`}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-full w-full bg-white object-contain"
    />
  );
}

function Detail({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div className="min-w-0 border-t border-line py-2.5 first:border-t-0">
      <dt className="text-[11px] font-semibold text-sub">{label}</dt>
      <dd className="mt-0.5 break-words text-[13px] font-semibold text-ink tnum">
        {value}
      </dd>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: NameCheckCandidate }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const status = candidate.applicationStatus ?? "상태 미제공";
  const kiprisUrl = candidate.applicationNumber
    ? `https://www.kipris.or.kr/khome/search/searchResult.do?queryText=${encodeURIComponent(candidate.applicationNumber)}`
    : null;

  return (
    <li className="overflow-hidden rounded-md border border-line bg-card">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={detailId}
        title={`${candidate.name} 선행상표 상세 ${open ? "접기" : "보기"}`}
        className="flex w-full items-center gap-3 p-3 text-left transition-colors hover:bg-bg"
      >
        <span className="h-14 w-14 shrink-0 overflow-hidden rounded-sm border border-line bg-white">
          <CandidateImage candidate={candidate} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="break-words text-[14px] font-extrabold text-ink">
              {candidate.name}
            </span>
            {candidate.exactTitleMatch && (
              <span className="rounded-sm bg-caution-bg px-1.5 py-0.5 text-[10px] font-bold text-caution-deep">
                명칭 일치
              </span>
            )}
            {candidate.isRegistered && (
              <span className="rounded-sm bg-review-bg px-1.5 py-0.5 text-[10px] font-bold text-review-deep">
                등록
              </span>
            )}
          </span>
          <span className="mt-1 block break-words text-[11.5px] text-sub">
            {[status, candidate.applicantName].filter(Boolean).join(" · ")}
          </span>
          {candidate.niceClasses.length > 0 && (
            <span className="mt-1 block text-[11px] font-semibold text-blue-dark">
              제 {candidate.niceClasses.join("·")}류
            </span>
          )}
        </span>
        <ChevronDown
          aria-hidden
          size={18}
          className={`shrink-0 text-sub transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div id={detailId} className="border-t border-line bg-bg/70 p-4">
          <div className="grid gap-4 sm:grid-cols-[148px_minmax(0,1fr)]">
            <div className="aspect-square w-full max-w-[148px] overflow-hidden rounded-sm border border-line bg-white">
              <CandidateImage candidate={candidate} />
            </div>
            <dl className="grid min-w-0 grid-cols-1 gap-x-5 sm:grid-cols-2">
              <Detail label="출원 상태" value={status} />
              <Detail label="출원번호" value={candidate.applicationNumber} />
              <Detail label="등록번호" value={candidate.registrationNumber} />
              <Detail label="출원인" value={candidate.applicantName} />
              <Detail label="권리자" value={candidate.rightHolderName} />
              <Detail label="표장 유형" value={candidate.markType} />
              <Detail label="출원일자" value={candidate.applicationDate} />
              <Detail label="등록일자" value={candidate.registrationDate} />
              <Detail
                label="상품류"
                value={
                  candidate.niceClasses.length
                    ? `제 ${candidate.niceClasses.join("·")}류`
                    : null
                }
              />
              <Detail
                label="유사군 코드"
                value={candidate.similarityCodes.join(", ") || null}
              />
              <Detail
                label="비엔나 코드"
                value={candidate.viennaCodes.join(", ") || null}
              />
            </dl>
          </div>
          <p className="mt-3 border-t border-line pt-3 text-[11px] leading-relaxed text-sub">
            명칭 일치는 등록 가능성이나 권리 충돌의 확정 판단이 아니며, 상품류와 권리
            상태를 함께 확인해야 해요.
          </p>
          {kiprisUrl && (
            <a
              href={kiprisUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-flex items-center gap-1.5 rounded-sm text-[12px] font-bold text-blue-dark underline decoration-line underline-offset-4 hover:decoration-blue-dark"
            >
              KIPRIS에서 원문 확인
              <ExternalLink aria-hidden size={14} />
            </a>
          )}
        </div>
      )}
    </li>
  );
}

function StatusDistribution({
  counts,
  partial,
}: {
  counts: Record<string, number>;
  partial: boolean;
}) {
  const entries = Object.entries(counts)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  if (!total) return null;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[12px] font-bold text-ink">
          {partial ? "확인 범위의 상태 분포" : "검색 상태 분포"}
        </p>
        <p className="text-[11px] text-sub tnum">확인 {total}건</p>
      </div>
      <div
        role="img"
        aria-label={`${partial ? "확인 범위, " : ""}${entries
          .map(([status, count]) => `${status} ${count}건`)
          .join(", ")}`}
        className="mt-2 flex h-2.5 w-full overflow-hidden rounded-sm bg-low-bg"
      >
        {entries.map(([status, count]) => (
          <span
            key={status}
            className={`${statusTone(status)} h-full`}
            style={{ width: `${(count / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5">
        {entries.map(([status, count]) => (
          <li key={status} className="flex items-center gap-1.5 text-[11px] text-sub">
            <span aria-hidden className={`h-2 w-2 rounded-sm ${statusTone(status)}`} />
            <span>{status}</span>
            <strong className="font-bold text-ink tnum">{count}</strong>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CountMetric({
  label,
  count,
  tone,
  lowerBound = false,
}: {
  label: string;
  count: number;
  tone: string;
  lowerBound?: boolean;
}) {
  return (
    <div className="bg-card px-2 py-3">
      <dt className="text-[10.5px] font-semibold text-sub">
        {label}
        {lowerBound && <span className="block text-[9px]">확인 범위</span>}
      </dt>
      <dd className={`mt-1 font-extrabold tnum ${tone}`}>
        {lowerBound && (
          <span className="mr-1 text-[9.5px] font-bold">
            {count > 0 ? "최소" : "확인"}
          </span>
        )}
        <span className="text-[19px]">{count}</span>
        <span className="ml-0.5 text-[11px]">건</span>
      </dd>
    </div>
  );
}

export default function NameCheckPanel({
  result,
  live = false,
  title = "명칭 검색 근거",
}: {
  result: NameCheckResult;
  live?: boolean;
  title?: string;
}) {
  const resultKey = `${result.normalizedName}-${result.checkedAt ?? "latest"}`;
  const [display, setDisplay] = useState({ key: resultKey, count: 6 });
  const visibleCount = display.key === resultKey ? display.count : 6;
  const visibleCandidates = result.candidates.slice(0, visibleCount);
  const remainingCandidates = Math.max(
    0,
    result.candidates.length - visibleCandidates.length,
  );
  const inspected = result.scannedCount ?? result.totalFound;
  const coveragePercent =
    result.totalFound > 0
      ? Math.min(100, Math.round((inspected / result.totalFound) * 100))
      : result.complete
        ? 100
        : 0;
  const available = result.available === true;
  const incomplete = result.complete !== true;
  const hasRegisteredMatch = result.exactRegisteredCount > 0;
  const tone = hasRegisteredMatch
    ? "text-caution-deep"
    : incomplete
      ? "text-review-deep"
      : available
      ? "text-safe-deep"
      : "text-caution-deep";

  return (
    <div>
      {live && (
        <p role="status" aria-live="polite" className="sr-only">
          명칭 검색 완료. {incomplete ? "일부 확인 범위에서 " : ""}동일 명칭 등록{" "}
          {result.exactRegisteredCount}건, 동일 명칭 전체 {result.exactTitleCount}건, 전체 검색{" "}
          {result.totalFound}건입니다.
        </p>
      )}
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
            hasRegisteredMatch
              ? "bg-caution-bg text-caution-deep"
              : incomplete
              ? "bg-review-bg text-review-deep"
              : available
                ? "bg-safe-bg text-safe-deep"
                : "bg-caution-bg text-caution-deep"
          }`}
        >
          {hasRegisteredMatch ? (
            <AlertTriangle size={17} />
          ) : incomplete ? (
            <Database size={17} />
          ) : available ? (
            <CheckCircle2 size={17} />
          ) : (
            <AlertTriangle size={17} />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-extrabold text-ink">{title}</h3>
          <p className={`mt-0.5 text-[14px] font-extrabold leading-snug ${tone}`}>
            {hasRegisteredMatch
              ? `동일 명칭의 등록상표를 ${incomplete ? "최소 " : ""}${result.exactRegisteredCount}건 확인했어요`
              : incomplete
                ? "검색 범위가 일부라 결론을 보류했어요"
              : available
                ? "정확히 같은 등록 명칭을 찾지 못했어요"
                : "같은 명칭의 선행상표를 확인했어요"}
          </p>
          <p className="mt-1 text-[12px] leading-relaxed text-sub">{result.message}</p>
        </div>
      </div>

      {incomplete && (
        <p className="mt-4 border-l-2 border-review bg-review-bg px-3 py-2 text-[11px] font-semibold leading-relaxed text-review-deep">
          검색이 끝나지 않아 아래 세 후보 건수는 확인 범위에서 발견된 최소값이에요.
        </p>
      )}

      <dl className={`${incomplete ? "mt-3" : "mt-4"} grid grid-cols-2 gap-px border border-line bg-line text-center sm:grid-cols-4`}>
        <CountMetric
          label="동일 명칭 등록"
          count={result.exactRegisteredCount}
          lowerBound={incomplete}
          tone={
            result.exactRegisteredCount > 0
              ? "text-caution-deep"
              : incomplete
                ? "text-review-deep"
                : "text-safe-deep"
          }
        />
        <CountMetric
          label="동일 명칭 전체"
          count={result.exactTitleCount}
          lowerBound={incomplete}
          tone={incomplete ? "text-review-deep" : "text-ink"}
        />
        <CountMetric
          label="등록 상태 후보"
          count={result.similarCount}
          lowerBound={incomplete}
          tone={result.similarCount > 0 || incomplete ? "text-review-deep" : "text-ink"}
        />
        <CountMetric
          label="전체 검색"
          count={result.totalFound}
          tone="text-blue-dark"
        />
      </dl>

      <div className="mt-3">
        <div className="flex items-center justify-between gap-3 text-[10.5px] text-sub">
          <span className="max-w-[65%] truncate">확인 이름 · {result.normalizedName}</span>
          <span className="shrink-0 tnum">
            {inspected}/{result.totalFound}건 확인
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="명칭 검색 범위"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={coveragePercent}
          className="mt-1.5 h-2 overflow-hidden rounded-sm bg-low-bg"
        >
          <span
            className="block h-full bg-blue-dark"
            style={{ width: `${coveragePercent}%` }}
          />
        </div>
      </div>

      <StatusDistribution counts={result.statusCounts} partial={incomplete} />

      {result.candidatesTruncated && (
        <p className="mt-3 border-l-2 border-review bg-review-bg px-3 py-2 text-[11px] font-semibold leading-relaxed text-review-deep">
          후보 상세는 응답 크기 제한으로 {result.candidatesReturned}건만 제공됐어요. 전체 검색
          건수와 상태 분포를 함께 확인해 주세요.
        </p>
      )}

      {result.candidates.length > 0 ? (
        <div className="mt-4 border-t border-line pt-4">
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-[12px] font-extrabold text-ink">선행상표 후보</h4>
            <span className="text-[10.5px] text-sub tnum">
              {result.candidatesReturned}건 표시
              {result.candidatesTruncated ? " · 일부" : ""}
            </span>
          </div>
          <ul className="mt-2 grid gap-2">
            {visibleCandidates.map((candidate) => (
              <CandidateRow key={candidate.id} candidate={candidate} />
            ))}
          </ul>
          {remainingCandidates > 0 && (
            <button
              type="button"
              onClick={() =>
                setDisplay({ key: resultKey, count: visibleCount + 10 })
              }
              className="press mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-line bg-card px-4 py-2.5 text-[12px] font-bold text-blue-dark hover:bg-blue-bg"
            >
              <ListPlus aria-hidden size={16} />
              후보 더 보기
              <span className="text-sub tnum">남은 {remainingCandidates}건</span>
            </button>
          )}
        </div>
      ) : result.exactTitleCount > 0 || result.similarCount > 0 ? (
        <p className="mt-4 border-t border-line pt-3 text-[11.5px] leading-relaxed text-sub">
          중복 건수는 확인했지만 상세 후보 데이터가 응답에 포함되지 않았어요.
        </p>
      ) : null}

      <p className="mt-3 text-[10.5px] text-sub">
        {result.source}
        {result.checkedAt ? ` · ${result.checkedAt}` : ""}
      </p>
    </div>
  );
}
