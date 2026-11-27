"use client";

import { useId, useState } from "react";
import { ChevronDown, Info, MessageSquareText, Pencil } from "lucide-react";
import type { SearchV2Candidate, SearchV2NameWord, SearchV2NameWords } from "@/lib/contracts";
import {
  CATEGORY_GOODS,
  type FamousBannerState,
  NOTICE_TEXT,
  allSmallLine,
  bigLine,
  categoryText,
  descriptiveNoticeKind,
  displayName,
  genericWords,
  moreWordsLine,
  someGenericLine,
  tipExample,
} from "@/lib/descriptiveNotice";

// 설명적 이름 안내(API 계약 v2 §2-7·§4-7). 응답의 name_words(질의 이름의 낱말별 식별력)로 —
//   큰 안내: 모든 낱말이 식별력 없는 말이고, 그 가운데 "흔히 쓰는 말"이 아닌 분류의 낱말이 하나 이상
//           있고, 유명 상표 배너(강함·약함)가 없을 때
//   작은 안내("자세히"): 모든 낱말이 식별력 없는 말인데 흔히 쓰는 말뿐이거나 유명 상표 배너가 있을 때
//   작은 안내("왜요?"): 일부 낱말만 그럴 때 — "빼고 비교했어요"가 보이는 후보 모두에서 사실일 때만
// 유명 상표 배너가 이름 쪽의 강한 일치(이름·이미지 속 글자)로 떴으면 어떤 안내도 그리지 않는다.
// name_words 가 없거나(이름 없는 질의·옛 서버) 식별력 없는 낱말이 없으면 아무것도 그리지 않는다.
// 문구는 lib/descriptiveNotice.ts 에 모았다. 질의에서 온 글자는 텍스트로만 그린다.

/** 낱말 목록 — "{낱말} — {분류 문구}", 싣지 않은 낱말은 "외 N개". */
function WordList({ words, more }: { words: SearchV2NameWord[]; more: number }) {
  return (
    <ul data-testid="descriptive-words" className="mt-2 flex flex-col gap-1">
      {words.map((word) => (
        <li key={word.word} className="break-words text-[12.5px] leading-relaxed text-ink">
          <span className="font-bold">{word.word}</span>
          {" — "}
          {categoryText(word.category)}
        </li>
      ))}
      {more > 0 && (
        <li data-testid="descriptive-more" className="text-[12px] text-sub">
          {moreWordsLine(more)}
        </li>
      )}
    </ul>
  );
}

function SmallNotice({
  line,
  toggle,
  words,
  more,
  follow,
  kind,
}: {
  line: string;
  toggle: string;
  words: SearchV2NameWord[];
  more: number;
  follow: string;
  kind: "all-small" | "some-small";
}) {
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const panelId = useId();
  return (
    <section
      aria-labelledby={headingId}
      data-testid="descriptive-notice"
      data-kind={kind}
      className="rounded-lg border border-line bg-card px-4 py-3"
    >
      <h2 id={headingId} className="sr-only">
        {NOTICE_TEXT.smallHeading}
      </h2>
      <div className="flex items-start gap-2">
        <Info aria-hidden size={15} className="mt-0.5 shrink-0 text-blue-dark" />
        <p className="min-w-0 flex-1 break-words text-[12.5px] leading-relaxed text-ink">
          <span data-testid="descriptive-line">{line}</span>{" "}
          <button
            type="button"
            data-testid="descriptive-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={() => setOpen((current) => !current)}
            className="press inline-flex items-center gap-0.5 rounded-sm text-[12px] font-bold text-blue-dark underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-dark"
          >
            {toggle}
            <ChevronDown
              aria-hidden
              size={13}
              className={`transition-transform ${open ? "rotate-180" : ""}`}
            />
          </button>
        </p>
      </div>
      <div id={panelId} hidden={!open} data-testid="descriptive-detail" className="pl-[23px]">
        <WordList words={words} more={more} />
        <p className="mt-2 break-words text-[12px] leading-relaxed text-sub">{follow}</p>
      </div>
    </section>
  );
}

export default function DescriptiveNotice({
  nameWords,
  candidates,
  queryName,
  famousBanner,
  onRename,
}: {
  /** 응답의 name_words — 없으면(이름 없는 질의·옛 서버) 그리지 않는다. */
  nameWords: SearchV2NameWords | undefined;
  /** 보이는 후보 — 일부 낱말만일 때 "빼고 비교했어요"가 사실인지 본다. */
  candidates: SearchV2Candidate[];
  /** 사용자가 넣은 이름 그대로("'{이름}'은(는) …"에 쓴다). */
  queryName?: string | null;
  /** 위의 유명 상표 배너 — 강함·약함 배너가 있으면 큰 안내 대신 작은 안내, 그 배너가 이름 쪽의 강한
   *  일치로 떴으면("name-strong") 아무것도 그리지 않는다. */
  famousBanner: FamousBannerState;
  /** "다른 이름으로 다시 확인하기" — 입력 화면으로 돌아가 이름 칸에 포커스. */
  onRename?: () => void;
}) {
  const headingId = useId();
  const kind = descriptiveNoticeKind(nameWords, famousBanner, candidates);
  if (!nameWords || !kind) return null;

  const words = genericWords(nameWords);
  const more = nameWords.more_generic;
  const name = displayName(queryName, nameWords);

  if (kind === "some-small") {
    return (
      <SmallNotice
        kind={kind}
        line={someGenericLine(
          words.map((word) => word.word),
          more,
        )}
        toggle={NOTICE_TEXT.someToggle}
        words={words}
        more={more}
        follow={NOTICE_TEXT.someFollow}
      />
    );
  }
  if (kind === "all-small") {
    return (
      <SmallNotice
        kind={kind}
        line={allSmallLine(name)}
        toggle={NOTICE_TEXT.allToggle}
        words={words}
        more={more}
        follow={NOTICE_TEXT.follow}
      />
    );
  }

  const goodsWord = words.find((word) => word.category === CATEGORY_GOODS);
  return (
    <section
      aria-labelledby={headingId}
      data-testid="descriptive-notice"
      data-kind={kind}
      className="rounded-lg border border-blue-dark/30 bg-blue-bg p-5"
    >
      <div className="flex items-start gap-3">
        <MessageSquareText aria-hidden size={20} className="mt-0.5 shrink-0 text-blue-dark" />
        <div className="min-w-0 flex-1">
          {/* 결과가 뜨면 포커스는 결과 화면의 제목(h1 "검색 결과")으로 간다(§4-10) — 이 제목은 그 아래 h2 */}
          <h2
            id={headingId}
            className="break-words text-[15px] font-extrabold leading-snug text-ink outline-none"
          >
            {NOTICE_TEXT.bigTitle}
          </h2>
          <p className="mt-1.5">
            <span
              data-testid="descriptive-label"
              className="inline-block rounded-full bg-card px-2 py-0.5 text-[10.5px] font-bold text-blue-dark"
            >
              {NOTICE_TEXT.bigLabel}
            </span>
          </p>
          <p
            data-testid="descriptive-line"
            className="mt-2 break-words text-[12.5px] leading-relaxed text-ink"
          >
            {bigLine(name)}
          </p>
          <WordList words={words} more={more} />
          <p className="mt-2 break-words text-[12.5px] leading-relaxed text-ink">
            {NOTICE_TEXT.follow}
          </p>
          <h3 className="mt-3 text-[12.5px] font-extrabold text-ink">{NOTICE_TEXT.tipsTitle}</h3>
          <ul data-testid="descriptive-tips" className="mt-1 flex list-disc flex-col gap-1 pl-4">
            <li className="break-words text-[12.5px] leading-relaxed text-ink">
              {NOTICE_TEXT.tipCoin}
              {goodsWord && (
                <>
                  {" "}
                  <span data-testid="descriptive-example">{tipExample(goodsWord.word)}</span>
                </>
              )}
            </li>
            <li className="break-words text-[12.5px] leading-relaxed text-ink">
              {NOTICE_TEXT.tipKeep}
            </li>
          </ul>
          {onRename && (
            <button
              type="button"
              data-testid="descriptive-retry"
              onClick={onRename}
              className="press mt-3 inline-flex items-center gap-1.5 rounded-md bg-blue-dark px-3.5 py-2 text-[12.5px] font-bold text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-dark"
            >
              <Pencil aria-hidden size={13} />
              {NOTICE_TEXT.retry}
            </button>
          )}
          <p
            data-testid="descriptive-footnote"
            className="mt-3 text-[10.5px] leading-relaxed text-sub"
          >
            {NOTICE_TEXT.footnote}
          </p>
        </div>
      </div>
    </section>
  );
}
