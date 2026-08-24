"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ImageCropDialog from "@/components/ImageCropDialog";
import NameCheckPanel from "@/components/NameCheckPanel";
import TurnstileWidget, {
  type TurnstileHandle,
} from "@/components/TurnstileWidget";
import {
  ApiError,
  checkTrademarkName,
} from "@/lib/api";
import type { NameCheckResult } from "@/lib/contracts";
import { useObjectUrl } from "@/lib/useObjectUrl";

const ACCEPTED = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 10 * 1024 * 1024;
const TOP_K_OPTIONS = [5, 10, 20] as const;

export interface SearchDraft {
  file: File;
  markName: string;
  topK: number;
  nameCheck?: NameCheckResult | null;
}

export interface SearchFormValue extends SearchDraft {
  turnstileToken: string;
}

type NamePhase =
  | { name: "idle" }
  | { name: "loading" }
  | { name: "result"; data: NameCheckResult }
  | { name: "error"; message: string };

export default function SearchForm({
  onSubmit,
  initialValue,
}: {
  onSubmit: (value: SearchFormValue) => void;
  initialValue?: SearchDraft | null;
}) {
  const [file, setFile] = useState<File | null>(initialValue?.file ?? null);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [markName, setMarkName] = useState(initialValue?.markName ?? "");
  const [topK, setTopK] = useState<number>(initialValue?.topK ?? 5);
  const [turnstileToken, setTurnstileToken] = useState<string | null>(null);
  const [namePhase, setNamePhase] = useState<NamePhase>(() =>
    initialValue?.nameCheck
      ? { name: "result", data: initialValue.nameCheck }
      : { name: "idle" },
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const turnstileRef = useRef<TurnstileHandle>(null);
  const nameAbortRef = useRef<AbortController | null>(null);
  const nameGenerationRef = useRef(0);
  const preview = useObjectUrl(file);
  const pendingPreview = useObjectUrl(pendingFile);

  const handleTokenChange = useCallback(
    (token: string | null) => setTurnstileToken(token),
    [],
  );

  useEffect(
    () => () => {
      nameGenerationRef.current += 1;
      nameAbortRef.current?.abort();
    },
    [],
  );

  const takeFile = (next: File | undefined) => {
    if (!next) return;
    setFileError(null);
    if (!ACCEPTED.includes(next.type)) {
      setFileError("PNG, JPG, WEBP 파일만 올릴 수 있어요.");
      return;
    }
    if (next.size > MAX_BYTES) {
      setFileError("파일이 너무 커요. 10MB 이하로 올려주세요.");
      return;
    }
    if (next.size === 0) {
      setFileError("빈 파일은 올릴 수 없어요.");
      return;
    }
    setPendingFile(next);
  };

  const runNameCheck = async () => {
    const name = markName.trim();
    if (!name) {
      setNamePhase({ name: "error", message: "확인할 상표 이름을 입력해 주세요." });
      return;
    }
    if (!turnstileToken) {
      setNamePhase({ name: "error", message: "자동 요청 확인이 끝날 때까지 기다려 주세요." });
      return;
    }

    nameAbortRef.current?.abort();
    const controller = new AbortController();
    nameAbortRef.current = controller;
    const generation = ++nameGenerationRef.current;
    const token = turnstileToken;
    setNamePhase({ name: "loading" });
    setTurnstileToken(null);

    try {
      const data = await checkTrademarkName(name, token, controller.signal);
      if (generation === nameGenerationRef.current) {
        setNamePhase({ name: "result", data });
      }
    } catch (error) {
      if (controller.signal.aborted || generation !== nameGenerationRef.current) return;
      setNamePhase({
        name: "error",
        message:
          error instanceof ApiError
            ? error.message
            : "이름을 확인하지 못했어요. 다시 시도해 주세요.",
      });
    } finally {
      turnstileRef.current?.reset();
    }
  };

  const submit = () => {
    if (!file || !turnstileToken) return;
    const token = turnstileToken;
    setTurnstileToken(null);
    turnstileRef.current?.reset();
    onSubmit({
      file,
      markName: markName.trim(),
      topK,
      nameCheck: namePhase.name === "result" ? namePhase.data : null,
      turnstileToken: token,
    });
  };

  return (
    <form
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <section className="rise px-1 pt-2">
        <h1
          data-phase-heading
          tabIndex={-1}
          className="text-[26px] font-extrabold leading-snug tracking-normal outline-none"
        >
          어떤 로고를
          <br />
          등록하고 싶으세요?
        </h1>
        <p className="mt-2 text-[14px] text-sub">
          로고 영역을 선택하면 등록상표와 얼마나 닮았는지 확인해요
        </p>
      </section>

      <section aria-labelledby="upload-title" className="rise rise-1 rounded-lg bg-card p-5">
        <h2 id="upload-title" className="sr-only">로고 이미지</h2>
        {preview && file ? (
          <div className="flex items-center gap-4">
            {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview */}
            <img
              src={preview}
              alt="선택한 로고 미리보기"
              className="h-20 w-20 rounded-md border border-line bg-white object-contain"
            />
            <div className="min-w-0 flex-1">
              <p className="truncate text-[15px] font-bold">{file.name}</p>
              <p className="mt-0.5 text-[12px] text-sub tnum">
                {(file.size / 1024).toFixed(0)}KB · 편집 완료
              </p>
            </div>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="press shrink-0 rounded-md bg-low-bg px-4 py-2 text-[13px] font-semibold text-sub"
            >
              변경
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              takeFile(event.dataTransfer.files?.[0]);
            }}
            aria-describedby="upload-help"
            className={`press w-full rounded-md border-2 border-dashed p-8 text-center transition-colors ${
              dragging ? "border-blue-dark bg-blue-bg" : "border-line bg-bg hover:border-faint"
            }`}
          >
            <span className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-blue-bg text-[22px] font-bold text-blue-dark" aria-hidden>
              +
            </span>
            <span className="block text-[15px] font-bold">로고 이미지 선택</span>
            <span id="upload-help" className="mt-1 block text-[12px] text-sub">
              사진과 화면 캡처 지원 · PNG · JPG · WEBP · 10MB 이하
            </span>
          </button>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="sr-only"
          tabIndex={-1}
          onChange={(event) => {
            takeFile(event.target.files?.[0] ?? undefined);
            event.currentTarget.value = "";
          }}
        />
        {fileError && (
          <p role="alert" className="mt-3 rounded-md bg-caution-bg px-4 py-2.5 text-[13px] font-semibold text-caution-deep">
            {fileError}
          </p>
        )}
      </section>

      <section aria-labelledby="name-title" className="rise rise-2 rounded-lg bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label id="name-title" htmlFor="mark-name" className="text-[13px] font-semibold text-sub">
            상표 이름
          </label>
          <span className="rounded-full bg-blue-bg px-2.5 py-0.5 text-[11px] font-bold text-blue-dark">
            KIPRIS 이름 확인
          </span>
        </div>
        <div className="mt-2 flex items-end gap-2">
          <input
            id="mark-name"
            type="text"
            value={markName}
            maxLength={100}
            aria-describedby="name-help"
            onChange={(event) => {
              nameGenerationRef.current += 1;
              nameAbortRef.current?.abort();
              setMarkName(event.target.value);
              setNamePhase({ name: "idle" });
            }}
            placeholder="예: 몬테로사 MONTEROSA"
            className="min-w-0 flex-1 border-b-2 border-line pb-2 text-[17px] font-bold outline-none placeholder:font-medium placeholder:text-placeholder focus:border-blue-dark"
          />
          <button
            type="button"
            onClick={runNameCheck}
            disabled={!markName.trim() || !turnstileToken || namePhase.name === "loading"}
            className="press shrink-0 rounded-md bg-low-bg px-4 py-2 text-[13px] font-bold text-sub disabled:text-disabled-text"
          >
            {namePhase.name === "loading" ? "확인 중" : "이름 확인"}
          </button>
        </div>
        <p id="name-help" className="mt-2 text-[11px] leading-relaxed text-sub">
          이미지 유사도와 별도로 동일·유사 명칭의 검색 범위를 확인해요.
        </p>
        {namePhase.name === "result" && (
          <div className="mt-4 border-t border-line pt-4">
            <NameCheckPanel result={namePhase.data} live />
          </div>
        )}
        {namePhase.name === "loading" && (
          <p role="status" aria-live="polite" className="sr-only">
            상표 이름을 확인하고 있습니다.
          </p>
        )}
        {namePhase.name === "error" && (
          <p role="alert" className="mt-3 text-[12px] font-semibold text-caution-deep">
            {namePhase.message}
          </p>
        )}
      </section>

      <section aria-labelledby="count-title" className="rise rise-3 rounded-lg bg-card p-5">
        <h2 id="count-title" className="text-[13px] font-semibold text-sub">
          비슷한 상표를 몇 개까지 볼까요?
        </h2>
        <div role="group" aria-label="검색 결과 개수" className="mt-3 grid grid-cols-3 gap-2 rounded-md bg-bg p-1.5">
          {TOP_K_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={topK === value}
              onClick={() => setTopK(value)}
              className={`press rounded-md py-2 text-[14px] font-bold tnum ${
                topK === value ? "bg-card text-blue-dark shadow-sm" : "text-sub"
              }`}
            >
              {value}개
            </button>
          ))}
        </div>
      </section>

      <section aria-labelledby="verification-title" className="rise rise-3 rounded-lg bg-card p-5">
        <h2 id="verification-title" className="mb-3 text-[13px] font-semibold text-sub">
          자동 요청 확인
        </h2>
        <TurnstileWidget ref={turnstileRef} onTokenChange={handleTokenChange} />
      </section>

      <div className="rise rise-3 mt-1">
        <button
          type="submit"
          disabled={!file || !turnstileToken || namePhase.name === "loading"}
          className="press w-full rounded-md bg-blue-dark py-4 text-[16px] font-bold text-white hover:bg-[#174ea6] disabled:bg-disabled disabled:text-disabled-text"
        >
          비슷한 상표 찾아보기
        </button>
        <p className="mt-3 text-center text-[11px] leading-relaxed text-sub">
          결과는 법적 판단이 아닌 참고 정보이며, 업로드 이미지는 검색 요청에만 사용돼요.
        </p>
      </div>

      {pendingFile && pendingPreview && (
        <ImageCropDialog
          file={pendingFile}
          sourceUrl={pendingPreview}
          onApply={(cropped) => {
            setFile(cropped);
            setPendingFile(null);
            setFileError(null);
          }}
          onCancel={() => setPendingFile(null)}
        />
      )}
    </form>
  );
}
