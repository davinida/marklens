"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ChevronDown, HelpCircle, LayoutGrid, Search, X } from "lucide-react";
import { ApiError, fetchGoodsClasses, searchGoods } from "@/lib/api";
import type { BusinessPreset, GoodsClass, GoodsMatch } from "@/lib/contracts";
import {
  addPresetGoods,
  addSelectedGood,
  FREQUENT_PRESETS,
  goodsCodeUnion,
  MAX_SELECTED_GOODS,
  removeSelectedGood,
  selectedGoodKey,
  type SelectedGood,
} from "@/lib/goods";

// TODO(프론트-6 후속): 동의어 검색(카페 → 커피전문점업)은 범위 밖. 변환표 aliases 는 제35류 병합 명칭뿐이라
// 지금은 고시상품명칭 부분 일치 + 업종 세트(business_presets.json)의 별칭 일치만 된다.

export const DEBOUNCE_MS = 250;
export const MIN_QUERY_LENGTH = 2;
const PAGE_SIZE = 20;
const PRODUCT_CLASS_MAX = 34; // 1~34류 상품, 35~45류 서비스
const DESKTOP_QUERY = "(min-width: 640px)";
export const SIMILARITY_GROUP_HELP =
  "유사군: 특허청이 서로 비슷한 상품끼리 묶어 둔 심사 기준 그룹이에요. 같은 그룹이면 상품이 비슷하다고 봐요.";

type SearchState =
  | { name: "loading" }
  | { name: "result"; matches: GoodsMatch[]; total: number; presets: BusinessPreset[] }
  | { name: "error"; message: string };

type Listing = { niceClass: number; items: GoodsMatch[]; total: number };

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "요청이 잦아요. 잠시 후 다시 시도해 주세요.";
    return error.message;
  }
  return fallback;
}

/** 데스크톱(sm 이상)이면 true. matchMedia 가 없는 환경(테스트)은 모바일로 본다. */
function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const media = window.matchMedia(DESKTOP_QUERY);
      media.addEventListener("change", onChange);
      return () => media.removeEventListener("change", onChange);
    },
    () =>
      typeof window !== "undefined" && !!window.matchMedia
        ? window.matchMedia(DESKTOP_QUERY).matches
        : false,
    () => false,
  );
}

function ClassBadge({ niceClass }: { niceClass: number }) {
  return (
    <span className="shrink-0 rounded-sm bg-low-bg px-1.5 py-0.5 text-[10px] font-bold text-sub tnum">
      제{niceClass}류
    </span>
  );
}

function ClassGroup({
  title,
  classes,
  open,
  onToggle,
  selectedClass,
  onSelect,
}: {
  title: string;
  classes: GoodsClass[];
  open: boolean;
  onToggle: () => void;
  selectedClass: number | null;
  onSelect: (niceClass: number) => void;
}) {
  const id = useId();
  return (
    <div className="mt-2">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-2 py-1 text-left text-[11.5px] font-bold text-ink"
      >
        {title}
        <ChevronDown
          aria-hidden
          size={14}
          className={`shrink-0 text-sub transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div id={id} role="group" aria-label={title} className="mt-1 flex flex-wrap gap-1.5">
          {classes.map((item) => {
            const pressed = selectedClass === item.nice_class;
            return (
              <button
                key={item.nice_class}
                type="button"
                aria-pressed={pressed}
                onClick={() => onSelect(item.nice_class)}
                className={`press rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                  pressed ? "bg-blue-dark text-white" : "bg-card text-ink"
                }`}
              >
                제{item.nice_class}류 {item.title}{" "}
                <span className={`ml-1 tnum ${pressed ? "text-white/80" : "text-sub"}`}>
                  {item.count.toLocaleString()}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * 지정상품 입력(프론트-6): 상품명 검색(디바운스·2글자 이상), 업종 세트 카드(v1.1), 자주 찾는 업종 칩,
 * 류 탐색(상품/서비스 두 묶음)으로 변환표 항목을 여러 개 고른다. 선택 상태는 부모(SearchForm)가 들고
 * 있어 이름 확인·이미지 검색을 해도 유지된다.
 */
export default function GoodsPicker({
  value,
  onChange,
  describedBy,
  max = MAX_SELECTED_GOODS,
}: {
  value: SelectedGood[];
  onChange: (next: SelectedGood[]) => void;
  describedBy?: string;
  max?: number;
}) {
  const baseId = useId();
  const listboxId = `${baseId}-listbox`;
  const helpId = `${baseId}-help`;
  const inputRef = useRef<HTMLInputElement>(null);
  const isDesktop = useIsDesktop();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState<SearchState | null>(null);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [notice, setNotice] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [classes, setClasses] = useState<GoodsClass[] | null>(null);
  const [classesError, setClassesError] = useState<string | null>(null);
  const [selectedClass, setSelectedClass] = useState<number | null>(null);
  const [productsOpen, setProductsOpen] = useState<boolean | null>(null);
  const [servicesOpen, setServicesOpen] = useState<boolean | null>(null);
  const [listing, setListing] = useState<Listing | null>(null);
  const [listingError, setListingError] = useState<string | null>(null);
  const [appending, setAppending] = useState(false);

  const trimmed = query.trim();
  const searching = trimmed.length >= MIN_QUERY_LENGTH;
  const showShortHint = trimmed.length > 0 && !searching;
  const codes = useMemo(() => goodsCodeUnion(value), [value]);
  const selectedKeys = useMemo(() => new Set(value.map(selectedGoodKey)), [value]);
  // 모바일 기본: 상품 묶음 접힘·서비스 묶음 펼침. 데스크톱은 둘 다 펼침. 사용자가 누르면 그 값을 따른다.
  const productsExpanded = productsOpen ?? isDesktop;
  const servicesExpanded = servicesOpen ?? true;

  // 상품명 검색 — 250ms 디바운스, 2글자 이상에서만 호출. 류를 골라 두면 그 류 안에서 찾는다.
  useEffect(() => {
    if (!searching) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setSearch({ name: "loading" });
      setOpen(true);
      try {
        const data = await searchGoods(trimmed, {
          limit: PAGE_SIZE,
          niceClass: selectedClass ?? undefined,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        setSearch({
          name: "result",
          matches: data.matches,
          total: data.total,
          presets: data.presets,
        });
        setActiveIndex(data.matches.length > 0 ? 0 : -1);
      } catch (error) {
        if (controller.signal.aborted) return;
        setSearch({
          name: "error",
          message: errorMessage(error, "상품을 검색하지 못했어요. 다시 시도해 주세요."),
        });
      }
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [trimmed, searching, selectedClass]);

  // "분류로 찾기"를 켜면 45개 류 목록을 한 번 받아 둔다.
  useEffect(() => {
    if (!browsing || classes !== null) return;
    const controller = new AbortController();
    fetchGoodsClasses(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setClasses(data.classes);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setClassesError(errorMessage(error, "상품 분류 목록을 불러오지 못했어요."));
      });
    return () => controller.abort();
  }, [browsing, classes]);

  // 류를 고르고 검색어가 없으면 그 류의 항목을 이름순으로 나열한다(검색어 없이 고르는 경로).
  const listingActive = browsing && selectedClass !== null && !searching;
  useEffect(() => {
    if (!listingActive || selectedClass === null) return;
    const controller = new AbortController();
    searchGoods(null, {
      niceClass: selectedClass,
      offset: 0,
      limit: PAGE_SIZE,
      signal: controller.signal,
    })
      .then((data) => {
        if (controller.signal.aborted) return;
        setListing({ niceClass: selectedClass, items: data.matches, total: data.total });
        setListingError(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setListingError(errorMessage(error, "상품 목록을 불러오지 못했어요. 다시 시도해 주세요."));
      });
    return () => controller.abort();
  }, [listingActive, selectedClass]);
  const currentListing = listing && listing.niceClass === selectedClass ? listing : null;
  const listingLoading = listingActive && currentListing === null && listingError === null;

  const loadMore = async () => {
    if (!currentListing || selectedClass === null) return;
    const niceClass = selectedClass;
    setAppending(true);
    try {
      const data = await searchGoods(null, {
        niceClass,
        offset: currentListing.items.length,
        limit: PAGE_SIZE,
      });
      setListing((previous) =>
        previous && previous.niceClass === niceClass
          ? { ...previous, items: [...previous.items, ...data.matches], total: data.total }
          : previous,
      );
      setListingError(null);
    } catch (error) {
      setListingError(errorMessage(error, "상품 목록을 불러오지 못했어요. 다시 시도해 주세요."));
    } finally {
      setAppending(false);
    }
  };

  const select = useCallback(
    (match: SelectedGood) => {
      const result = addSelectedGood(value, match, max);
      if (!result.added) {
        setNotice(
          result.reason === "limit"
            ? `지정상품은 최대 ${max}개까지 고를 수 있어요.`
            : "이미 고른 상품이에요.",
        );
        return;
      }
      setNotice(null);
      onChange(result.next);
    },
    [value, onChange, max],
  );

  const addPreset = useCallback(
    (preset: BusinessPreset) => {
      const result = addPresetGoods(value, preset.지정상품, max);
      if (result.added > 0) onChange(result.next);
      if (result.overLimit > 0) {
        setNotice(`지정상품은 최대 ${max}개까지라 ${result.overLimit}개는 추가하지 못했어요.`);
      } else if (result.added === 0) {
        setNotice("이미 모두 고른 상품이에요.");
      } else {
        setNotice(null);
      }
    },
    [value, onChange, max],
  );

  const options = searching && search?.name === "result" ? search.matches : [];
  const presets = searching && search?.name === "result" ? search.presets : [];
  const dropdownOpen = open && searching && search !== null;

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (options.length === 0) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : options.length - 1;
      setActiveIndex((index) => (index < 0 ? 0 : (index + step) % options.length));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault(); // 검색 폼 제출 방지
      if (dropdownOpen && activeIndex >= 0 && options[activeIndex]) select(options[activeIndex]);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault(); // type=search 의 기본 동작(입력값 지우기)을 막고 드롭다운만 닫는다
      setOpen(false);
    }
  };

  const activeId = dropdownOpen && activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined;
  const keepFocus = (event: React.MouseEvent) => event.preventDefault(); // 드롭다운 클릭 시 blur 방지
  const productClasses = classes?.filter((item) => item.nice_class <= PRODUCT_CLASS_MAX) ?? [];
  const serviceClasses = classes?.filter((item) => item.nice_class > PRODUCT_CLASS_MAX) ?? [];

  return (
    <div data-goods-picker>
      <div className="relative">
        <div className="mt-2 flex items-end gap-2">
          <div className="relative min-w-0 flex-1">
            <Search
              aria-hidden
              size={16}
              className="pointer-events-none absolute left-0 top-1/2 -translate-y-1/2 text-sub"
            />
            {/* type=search + autoComplete=off: Safari 연락처 자동완성 아이콘 방지.
                검색창 기본 모양과 WebKit/Chrome 의 지우기(x) 버튼은 끈다. */}
            <input
              ref={inputRef}
              type="search"
              autoComplete="off"
              role="combobox"
              aria-label="지정상품 검색"
              aria-expanded={dropdownOpen}
              aria-controls={dropdownOpen ? listboxId : undefined}
              aria-activedescendant={activeId}
              aria-autocomplete="list"
              aria-describedby={describedBy}
              value={query}
              maxLength={50}
              placeholder="예: 커피, 화장품, 의류 — 또는 업종(카페, 치킨집)"
              onChange={(event) => {
                setQuery(event.target.value);
                setNotice(null);
              }}
              onKeyDown={onKeyDown}
              onFocus={() => {
                if (search !== null) setOpen(true);
              }}
              onBlur={() => setOpen(false)}
              className="w-full appearance-none border-b-2 border-line pb-2 pl-6 text-[15px] font-bold outline-none placeholder:font-medium placeholder:text-placeholder focus:border-blue-dark [&::-webkit-search-cancel-button]:appearance-none"
            />
          </div>
          <button
            type="button"
            aria-pressed={browsing}
            onClick={() => setBrowsing((value) => !value)}
            className={`press inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-2 text-[12px] font-bold ${
              browsing ? "bg-blue-bg text-blue-dark" : "bg-low-bg text-sub"
            }`}
          >
            <LayoutGrid aria-hidden size={14} />
            분류로 찾기
          </button>
        </div>

        {showShortHint && (
          <p className="mt-1.5 text-[11px] text-sub">2글자 이상 입력하면 검색해요.</p>
        )}

        {trimmed.length === 0 && (
          <div className="mt-2">
            <p className="text-[11px] font-semibold text-sub">자주 찾는 업종</p>
            <div role="group" aria-label="자주 찾는 업종" className="mt-1 flex flex-wrap gap-1.5">
              {FREQUENT_PRESETS.map((chip) => (
                <button
                  key={chip.id}
                  type="button"
                  onClick={() => {
                    setQuery(chip.query);
                    setNotice(null);
                    inputRef.current?.focus();
                  }}
                  className="press rounded-full bg-low-bg px-2.5 py-1 text-[11.5px] font-semibold text-ink hover:bg-blue-bg"
                >
                  <span aria-hidden>{chip.emoji} </span>
                  {chip.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {dropdownOpen && search && (
          <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-96 overflow-auto rounded-md border border-line bg-card shadow-lg">
            {search.name === "loading" && (
              <p role="status" aria-live="polite" className="px-3 py-2 text-[12px] text-sub">
                상품을 찾는 중이에요.
              </p>
            )}
            {search.name === "error" && (
              <p role="alert" className="px-3 py-2 text-[12px] font-semibold text-caution-deep">
                {search.message}
              </p>
            )}
            {presets.map((preset) => {
              const allChosen = preset.지정상품.every((good) =>
                selectedKeys.has(selectedGoodKey(good)),
              );
              return (
                <section
                  key={preset.id}
                  aria-label={`${preset.업종명} 업종 세트`}
                  className="border-b border-line bg-blue-bg/40 px-3 py-2.5"
                >
                  {/* 글은 남은 폭을 채우고(14rem 미만이면 버튼이 다음 줄로), 버튼은 줄바꿈·축소 없이 */}
                  <div className="flex flex-wrap items-start justify-between gap-x-2 gap-y-1.5">
                    <p className="min-w-0 grow basis-56 text-[12.5px] leading-snug text-ink">
                      <span className="font-extrabold">
                        <span aria-hidden>{preset.emoji ? `${preset.emoji} ` : ""}</span>
                        {preset.업종명} 업종
                      </span>
                      <span className="text-sub">
                        {" — "}
                        {preset.지정상품
                          .map((good) => `${good.name}(${good.nice_class}류)`)
                          .join(" · ")}
                      </span>
                    </p>
                    <button
                      type="button"
                      disabled={allChosen}
                      onMouseDown={keepFocus}
                      onClick={() => addPreset(preset)}
                      className="press shrink-0 whitespace-nowrap rounded-md bg-blue-dark px-2.5 py-1.5 text-[11.5px] font-bold text-white disabled:bg-disabled disabled:text-disabled-text"
                    >
                      {allChosen ? "모두 선택됨" : `${preset.지정상품.length}개 모두 추가`}
                    </button>
                  </div>
                  {preset.hint && (
                    <p className="mt-1 text-[11px] leading-relaxed text-sub">{preset.hint}</p>
                  )}
                  <ul aria-label={`${preset.업종명} 업종 세트 항목`} className="mt-1.5 flex flex-wrap gap-1.5">
                    {preset.지정상품.map((good) => {
                      const chosen = selectedKeys.has(selectedGoodKey(good));
                      return (
                        <li key={selectedGoodKey(good)}>
                          <button
                            type="button"
                            disabled={chosen}
                            aria-label={chosen ? `${good.name} 선택됨` : `${good.name} 추가`}
                            onMouseDown={keepFocus}
                            onClick={() => select(good)}
                            className="press inline-flex items-center gap-1 rounded-full border border-line bg-card px-2 py-0.5 text-[11.5px] font-semibold text-ink disabled:text-disabled-text"
                          >
                            {good.name} <ClassBadge niceClass={good.nice_class} />
                            {chosen ? (
                              <span className="text-[10px] text-sub">선택됨</span>
                            ) : (
                              <span className="text-[10px] font-bold text-blue-dark">추가</span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })}
            {search.name === "result" && search.matches.length === 0 && (
              <p className="px-3 py-2 text-[12px] text-sub">
                일치하는 상품명이 없어요. 다른 표현이나 분류로 찾아보세요.
              </p>
            )}
            {search.name === "result" && search.matches.length > 0 && (
              <>
                {search.total > search.matches.length && (
                  <p className="border-b border-line px-3 py-1.5 text-[11px] text-sub tnum">
                    {search.total.toLocaleString()}건 중 {search.matches.length}건 — 더 구체적으로
                    입력해 보세요.
                  </p>
                )}
                <ul id={listboxId} role="listbox" aria-label="상품명 검색 결과">
                  {search.matches.map((match, index) => {
                    const key = selectedGoodKey(match);
                    const chosen = selectedKeys.has(key);
                    return (
                      <li
                        key={key}
                        id={`${listboxId}-${index}`}
                        role="option"
                        aria-selected={index === activeIndex}
                        onMouseDown={keepFocus}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => select(match)}
                        className={`flex cursor-pointer flex-wrap items-center gap-x-2 gap-y-0.5 px-3 py-2 text-[13px] ${
                          index === activeIndex ? "bg-blue-bg" : ""
                        }`}
                      >
                        {/* 접근성 이름이 "커피 제30류 …"로 읽히도록 조각 사이에 공백을 둔다 */}
                        <span className="break-words font-bold text-ink">{match.name}</span>{" "}
                        <ClassBadge niceClass={match.nice_class} />{" "}
                        {match.matched_alias && (
                          <span className="text-[11px] text-sub">고시 명칭: {match.matched_alias}</span>
                        )}{" "}
                        {chosen && (
                          <span className="text-[11px] font-semibold text-blue-dark">선택됨</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </>
            )}
          </div>
        )}
      </div>

      {browsing && (
        <div className="mt-3 rounded-md border border-line bg-bg p-3">
          <p className="text-[11px] font-semibold text-sub">
            분류(류)를 고르면 그 류 안에서 검색하거나 목록에서 바로 고를 수 있어요. 1~34류는 상품,
            35~45류는 서비스예요.
          </p>
          {classesError && (
            <p role="alert" className="mt-2 text-[12px] font-semibold text-caution-deep">
              {classesError}
            </p>
          )}
          {!classes && !classesError && (
            <p role="status" aria-live="polite" className="mt-2 text-[12px] text-sub">
              상품 분류를 불러오는 중이에요.
            </p>
          )}
          {classes && (
            <>
              <ClassGroup
                title="상품(1~34류)"
                classes={productClasses}
                open={productsExpanded}
                onToggle={() => setProductsOpen(!productsExpanded)}
                selectedClass={selectedClass}
                onSelect={(niceClass) =>
                  setSelectedClass((current) => (current === niceClass ? null : niceClass))
                }
              />
              <ClassGroup
                title="서비스(35~45류)"
                classes={serviceClasses}
                open={servicesExpanded}
                onToggle={() => setServicesOpen(!servicesExpanded)}
                selectedClass={selectedClass}
                onSelect={(niceClass) =>
                  setSelectedClass((current) => (current === niceClass ? null : niceClass))
                }
              />
            </>
          )}
          {selectedClass !== null && searching && (
            <p className="mt-2 text-[11px] text-sub">제{selectedClass}류 안에서 검색해요.</p>
          )}
          {selectedClass !== null && !searching && (
            <div className="mt-2">
              {listingError && (
                <p role="alert" className="text-[12px] font-semibold text-caution-deep">
                  {listingError}
                </p>
              )}
              {listingLoading && (
                <p role="status" aria-live="polite" className="text-[12px] text-sub">
                  목록을 불러오는 중이에요.
                </p>
              )}
              {currentListing && currentListing.items.length > 0 && (
                <ul
                  aria-label={`제${selectedClass}류 상품 목록`}
                  className="divide-y divide-line rounded-md border border-line bg-card"
                >
                  {currentListing.items.map((item) => (
                    <li key={selectedGoodKey(item)}>
                      <button
                        type="button"
                        aria-label={`${item.name} 추가`}
                        onClick={() => select(item)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] hover:bg-bg"
                      >
                        <span className="break-words font-semibold text-ink">{item.name}</span>
                        <span className="shrink-0 text-[11px] font-bold text-blue-dark">
                          {selectedKeys.has(selectedGoodKey(item)) ? "선택됨" : "추가"}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {currentListing && currentListing.items.length === 0 && (
                <p className="text-[12px] text-sub">이 류에는 변환표 항목이 없어요.</p>
              )}
              {currentListing && currentListing.items.length < currentListing.total && (
                <button
                  type="button"
                  disabled={appending}
                  onClick={() => void loadMore()}
                  className="press mt-2 w-full rounded-md border border-line bg-card px-3 py-2 text-[12px] font-bold text-blue-dark disabled:text-disabled-text"
                >
                  {appending ? "불러오는 중" : "더 보기"}
                  <span className="ml-1 text-sub tnum">
                    남은 {(currentListing.total - currentListing.items.length).toLocaleString()}건
                  </span>
                </button>
              )}
              {currentListing && currentListing.total > 0 && (
                <p className="mt-1 text-[10.5px] text-sub tnum">
                  {currentListing.items.length}/{currentListing.total.toLocaleString()}건
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {value.length > 0 && (
        <div className="mt-3">
          <ul aria-label="선택한 지정상품" className="flex flex-wrap gap-1.5">
            {value.map((good) => (
              <li
                key={selectedGoodKey(good)}
                className="inline-flex max-w-full items-center gap-1 rounded-full bg-blue-bg py-1 pl-2.5 pr-1 text-[12px] font-semibold text-blue-dark"
              >
                <span className="truncate">{good.name}</span>{" "}
                <ClassBadge niceClass={good.nice_class} />{" "}
                <button
                  type="button"
                  aria-label={`${good.name} 제거`}
                  onClick={() => {
                    setNotice(null);
                    onChange(removeSelectedGood(value, good));
                  }}
                  className="press rounded-full p-0.5 hover:bg-card"
                >
                  <X aria-hidden size={13} />
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-2 flex items-center gap-1.5 text-[11px] text-sub">
            <details className="min-w-0">
              <summary className="cursor-pointer font-semibold text-ink">유사군 {codes.length}개</summary>
              <p className="mt-1 break-words tnum">{codes.join(", ")}</p>
            </details>
            <button
              type="button"
              aria-label="유사군 설명"
              aria-expanded={helpOpen}
              aria-controls={helpId}
              onClick={() => setHelpOpen((open) => !open)}
              className="press rounded-full p-0.5 text-sub hover:text-blue-dark"
            >
              <HelpCircle aria-hidden size={14} />
            </button>
          </div>
          {helpOpen && (
            <p id={helpId} className="mt-1 rounded-md bg-bg px-3 py-2 text-[11px] leading-relaxed text-sub">
              {SIMILARITY_GROUP_HELP}
            </p>
          )}
        </div>
      )}

      {notice && (
        <p role="status" aria-live="polite" className="mt-2 text-[11px] font-semibold text-caution-deep">
          {notice}
        </p>
      )}
    </div>
  );
}
