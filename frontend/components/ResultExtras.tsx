"use client";

import { useId } from "react";
import { Camera, PencilLine, Type } from "lucide-react";
import { josaEulReul } from "@/lib/josa";
import {
  LOGO_ONLY_TEXT,
  PHOTO_NOTICE_LABEL,
  QUERY_SUMMARY_TEXT,
  goodsSummary,
  oneLine,
  shorten,
  type LogoOnlyNoticeKind,
  type QuerySummaryInput,
} from "@/lib/resultExtras";

// 결과 화면의 보완(API 계약 v2 §4-9) — 로고만 넣은 검색의 상표명 입력 안내, 사진 안내, 검색 내용 한 줄.
// 문구와 규칙은 lib/resultExtras.ts 에 모았다. 질의에서 온 글자(이름·로고에서 읽은 글자·업종 이름)는
// 텍스트로만 그린다.

/** 로고만 넣은 검색의 상표명 입력 안내 — 맨 위 안내 영역의 마지막. 버튼은 입력 화면으로 돌아가 이름
 *  칸에 포커스를 둔다(A형은 읽은 글자를 채운다). 바로 다시 검색하지 않는다. */
export function LogoOnlyNotice({
  kind,
  suggestedName,
  onAddName,
}: {
  kind: LogoOnlyNoticeKind;
  /** 서버가 준 "로고에서 읽은 글자"(A형) */
  suggestedName?: string | null;
  /** 이름 칸에 채울 글자(없으면 null)를 넘긴다 */
  onAddName?: (name: string | null) => void;
}) {
  const read = kind === "read" ? oneLine(suggestedName ?? "") : "";
  const shown = shorten(read);
  const headingId = useId();

  return (
    <section
      aria-labelledby={headingId}
      data-testid="logo-only-notice"
      data-kind={kind}
      className="rounded-lg border border-blue-dark/30 bg-blue-bg p-5"
    >
      <h2 id={headingId} className="sr-only">
        {LOGO_ONLY_TEXT.label}
      </h2>
      <div className="flex items-start gap-3">
        <Type aria-hidden size={20} className="mt-0.5 shrink-0 text-blue-dark" />
        <div className="min-w-0 flex-1">
          <p
            data-testid="logo-only-line"
            className="break-words text-[13.5px] font-semibold leading-relaxed text-ink"
          >
            {kind === "read" ? (
              <>
                {LOGO_ONLY_TEXT.readLead}&apos;
                <span data-testid="logo-only-read" title={shown === read ? undefined : read}>
                  {shown}
                </span>
                &apos;{josaEulReul(read)}
                {LOGO_ONLY_TEXT.readTail}
              </>
            ) : (
              LOGO_ONLY_TEXT.plain
            )}
          </p>
          {onAddName && (
            <button
              type="button"
              data-testid="logo-only-button"
              onClick={() => onAddName(kind === "read" ? (suggestedName ?? null) : null)}
              className="press mt-3 inline-flex items-center gap-1.5 rounded-md bg-blue-dark px-3.5 py-2 text-[12.5px] font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-dark"
            >
              <PencilLine aria-hidden size={13} />
              {kind === "read" ? LOGO_ONLY_TEXT.readButton : LOGO_ONLY_TEXT.plainButton}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}

/** 사진으로 판정된 이미지의 안내 — 문장은 서버가 준 그대로(주의 목록에서 옮겨 온 것). */
export function PhotoNotice({ text }: { text: string }) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId}>
      <h2 id={headingId} className="sr-only">
        {PHOTO_NOTICE_LABEL}
      </h2>
      <p
        data-testid="photo-notice"
        className="flex items-start gap-2 rounded-lg border border-line bg-card px-4 py-3 text-[12.5px] leading-relaxed text-ink"
      >
        <Camera aria-hidden size={15} className="mt-0.5 shrink-0 text-blue-dark" />
        <span className="min-w-0 break-words">{text}</span>
      </p>
    </section>
  );
}

/** 검색 내용 한 줄 — 이름 · 로고 · 업종. 화면이 갖고 있는 입력 상태로만 그린다. */
export function QuerySummary({ query }: { query: QuerySummaryInput }) {
  const name = oneLine(query.name);
  const shownName = shorten(name);
  const goods = goodsSummary(query.goods);

  return (
    <p
      data-testid="query-summary"
      className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-1 text-[12px] leading-relaxed text-sub"
    >
      <span className="font-bold text-ink">{QUERY_SUMMARY_TEXT.label}</span>
      <span
        data-testid="query-summary-name"
        title={shownName === name ? undefined : name}
        className="min-w-0 break-all"
      >
        {name ? `'${shownName}'` : QUERY_SUMMARY_TEXT.noName}
      </span>
      <span aria-hidden>·</span>
      <span data-testid="query-summary-logo" className="inline-flex items-center">
        {query.logo ? (
          // eslint-disable-next-line @next/next/no-img-element -- local blob preview
          <img
            src={query.logo}
            alt={QUERY_SUMMARY_TEXT.logoAlt}
            className="h-6 w-6 rounded-sm border border-line bg-white object-contain"
          />
        ) : (
          QUERY_SUMMARY_TEXT.noLogo
        )}
      </span>
      <span aria-hidden>·</span>
      <span
        data-testid="query-summary-goods"
        title={query.goods.length > 3 ? query.goods.join(", ") : undefined}
        className="min-w-0 break-words"
      >
        {goods}
      </span>
    </p>
  );
}
