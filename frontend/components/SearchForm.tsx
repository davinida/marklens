"use client";

import { useCallback, useRef, useState } from "react";

/** 지정상품 추천 칩 — 프론트-2 변환표 확보 전까지의 임시 목록 */
const GOODS_SUGGESTIONS = ["커피", "화장품", "의류", "전자제품", "식당업"];

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;
const TOP_K_OPTIONS = [5, 10, 20] as const;

export interface SearchFormValue {
  file: File;
  markName: string;
  goods: string[];
  topK: number;
}

export default function SearchForm({
  onSubmit,
}: {
  onSubmit: (value: SearchFormValue) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [markName, setMarkName] = useState("");
  const [goods, setGoods] = useState<string[]>([]);
  const [goodsInput, setGoodsInput] = useState("");
  const [topK, setTopK] = useState<number>(5);
  const inputRef = useRef<HTMLInputElement>(null);

  const takeFile = useCallback(
    (f: File | undefined) => {
      if (!f) return;
      if (!ACCEPTED.includes(f.type)) {
        setFileError("PNG · JPG · WEBP 파일만 올릴 수 있어요.");
        return;
      }
      if (f.size > MAX_BYTES) {
        setFileError("파일이 너무 커요. 10MB 이하로 올려주세요.");
        return;
      }
      setFileError(null);
      setFile(f);
      if (preview) URL.revokeObjectURL(preview);
      setPreview(URL.createObjectURL(f));
    },
    [preview],
  );

  const addGoods = (g: string) => {
    const v = g.trim();
    if (!v || goods.includes(v)) return;
    setGoods((prev) => [...prev, v]);
    setGoodsInput("");
  };

  return (
    <div className="flex flex-col gap-3">
      <section className="rise px-1 pt-2">
        <h1 className="text-[26px] font-extrabold leading-snug tracking-tight">
          어떤 로고를
          <br />
          등록하고 싶으세요?
        </h1>
        <p className="mt-2 text-[14px] text-sub">
          로고를 올리면 등록상표와 얼마나 닮았는지 알려드려요
        </p>
      </section>

      {/* 로고 업로드 */}
      <section className="rise rise-1 rounded-[20px] bg-card p-5">
        {preview && file ? (
          <div className="flex items-center gap-4">
            {/* eslint-disable-next-line @next/next/no-img-element -- 로컬 blob 미리보기 */}
            <img
              src={preview}
              alt="업로드한 로고 미리보기"
              className="h-20 w-20 rounded-2xl border border-line object-contain bg-white"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[15px] font-bold">{file.name}</p>
              <p className="mt-0.5 text-[12px] text-muted tnum">
                {(file.size / 1024).toFixed(0)}KB · 준비 완료
              </p>
            </div>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="press shrink-0 rounded-full bg-low-bg px-4 py-2 text-[13px] font-semibold text-sub"
            >
              변경
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              takeFile(e.dataTransfer.files?.[0]);
            }}
            className={`press w-full rounded-2xl border-2 border-dashed p-8 text-center transition-colors ${
              dragging
                ? "border-blue bg-blue-bg"
                : "border-line bg-bg hover:border-faint"
            }`}
          >
            <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-blue-bg text-[22px] font-bold text-blue">
              +
            </span>
            <span className="block text-[15px] font-bold">
              로고 이미지 올리기
            </span>
            <span className="mt-1 block text-[12px] text-muted">
              누르거나 끌어다 놓기 · PNG · JPG · WEBP · 10MB 이하
            </span>
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="hidden"
          onChange={(e) => takeFile(e.target.files?.[0] ?? undefined)}
        />
        {fileError && (
          <p className="mt-3 rounded-xl bg-caution-bg px-4 py-2.5 text-[13px] font-semibold text-caution-deep">
            {fileError}
          </p>
        )}
      </section>

      {/* 상표명 — 현재 백엔드는 이미지만 사용, 다축 확장 대비 입력 UI */}
      <section className="rise rise-2 rounded-[20px] bg-card p-5">
        <div className="flex items-center justify-between">
          <label
            htmlFor="mark-name"
            className="text-[13px] font-semibold text-muted"
          >
            상표 이름
          </label>
          <span className="rounded-full bg-blue-bg px-2.5 py-0.5 text-[11px] font-bold text-blue-dark">
            다축 분석에 반영 예정
          </span>
        </div>
        <input
          id="mark-name"
          type="text"
          value={markName}
          onChange={(e) => setMarkName(e.target.value)}
          placeholder="예: 몬테로사 MONTEROSA"
          className="mt-2 w-full border-b-2 border-line pb-2 text-[17px] font-bold outline-none placeholder:font-medium placeholder:text-faint focus:border-blue"
        />
      </section>

      {/* 지정상품 */}
      <section className="rise rise-2 rounded-[20px] bg-card p-5">
        <div className="flex items-center justify-between">
          <label
            htmlFor="goods-input"
            className="text-[13px] font-semibold text-muted"
          >
            어디에 쓰는 상표인가요?
          </label>
          <span className="rounded-full bg-blue-bg px-2.5 py-0.5 text-[11px] font-bold text-blue-dark">
            유사군 변환 예정
          </span>
        </div>
        {goods.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {goods.map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGoods((prev) => prev.filter((x) => x !== g))}
                className="press rounded-full bg-blue px-3.5 py-1.5 text-[13px] font-bold text-white"
              >
                {g} ✕
              </button>
            ))}
          </div>
        )}
        <input
          id="goods-input"
          type="text"
          value={goodsInput}
          onChange={(e) => setGoodsInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addGoods(goodsInput);
            }
          }}
          placeholder="쉬운 말로 입력하고 Enter — 예: 커피"
          className="mt-2 w-full border-b-2 border-line pb-2 text-[15px] font-semibold outline-none placeholder:font-medium placeholder:text-faint focus:border-blue"
        />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {GOODS_SUGGESTIONS.filter((g) => !goods.includes(g)).map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => addGoods(g)}
              className="press rounded-full bg-low-bg px-3.5 py-1.5 text-[13px] font-semibold text-sub"
            >
              + {g}
            </button>
          ))}
        </div>
      </section>

      {/* 결과 개수 */}
      <section className="rise rise-3 rounded-[20px] bg-card p-5">
        <p className="text-[13px] font-semibold text-muted">
          비슷한 상표를 몇 개까지 볼까요?
        </p>
        <div className="mt-3 grid grid-cols-3 gap-2 rounded-2xl bg-bg p-1.5">
          {TOP_K_OPTIONS.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setTopK(k)}
              className={`press rounded-xl py-2 text-[14px] font-bold tnum ${
                topK === k ? "bg-card text-blue shadow-sm" : "text-muted"
              }`}
            >
              {k}개
            </button>
          ))}
        </div>
      </section>

      <div className="rise rise-3 mt-1">
        <button
          type="button"
          disabled={!file}
          onClick={() =>
            file && onSubmit({ file, markName, goods, topK })
          }
          className="press w-full rounded-2xl bg-blue py-4 text-[16px] font-bold text-white hover:bg-blue-dark disabled:bg-faint"
        >
          비슷한 상표 찾아보기
        </button>
        <p className="mt-3 text-center text-[11px] leading-relaxed text-muted">
          결과는 법적 판단이 아닌 참고 정보예요 · 상표 이름과 지정상품은
          <br />
          다축 모델(호칭·관념·상품 견련성) 확장 후 분석에 반영돼요
        </p>
      </div>
    </div>
  );
}
