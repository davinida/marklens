"use client";

import { useEffect, useRef, useState } from "react";
import ReactCrop, { type Crop, type PixelCrop } from "react-image-crop";
import "react-image-crop/dist/ReactCrop.css";
import { cropImageFile, fullImageCrop } from "@/lib/crop";

export default function ImageCropDialog({
  file,
  sourceUrl,
  onApply,
  onCancel,
}: {
  file: File;
  sourceUrl: string;
  onApply: (file: File) => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [crop, setCrop] = useState<Crop>({
    unit: "%",
    x: 5,
    y: 5,
    width: 90,
    height: 90,
  });
  const [completed, setCompleted] = useState<PixelCrop | null>(null);
  const [imageReady, setImageReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    return () => {
      if (dialog.open && typeof dialog.close === "function") dialog.close();
    };
  }, []);

  const finish = async (selection: PixelCrop) => {
    const image = imageRef.current;
    if (!image) return;
    setBusy(true);
    setError(null);
    try {
      onApply(await cropImageFile(image, selection, file.name));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "이미지를 편집할 수 없어요.");
      setBusy(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="crop-title"
      aria-describedby="crop-description"
      className="crop-dialog m-auto max-h-[calc(100dvh-1rem)] w-[min(92vw,720px)] overflow-y-auto overscroll-contain rounded-lg bg-card p-0 text-ink shadow-2xl"
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
    >
      <div className="border-b border-line px-5 py-4">
        <h2 id="crop-title" className="text-[18px] font-extrabold">
          분석할 로고 영역 선택
        </h2>
        <p id="crop-description" className="mt-1 text-[13px] text-sub">
          사진이나 화면 캡처에서 로고만 남도록 테두리를 움직여 주세요.
        </p>
      </div>

      <div className="flex min-h-[min(18rem,40dvh)] max-h-[52dvh] items-center justify-center overflow-auto bg-[#111827] p-4">
        <ReactCrop
          crop={crop}
          onChange={(_, percentCrop) => setCrop(percentCrop)}
          onComplete={(pixelCrop) => setCompleted(pixelCrop)}
          minWidth={32}
          minHeight={32}
          keepSelection
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- local blob crop source */}
          <img
            ref={imageRef}
            src={sourceUrl}
            alt="자를 원본 이미지"
            className="max-h-[calc(52dvh-2rem)] max-w-full object-contain"
            onLoad={(event) => {
              const image = event.currentTarget;
              setImageReady(true);
              setCompleted({
                unit: "px",
                x: image.width * 0.05,
                y: image.height * 0.05,
                width: image.width * 0.9,
                height: image.height * 0.9,
              });
            }}
            onError={() => {
              setImageReady(false);
              setCompleted(null);
              setError("이미지를 읽을 수 없어요. 다른 파일을 선택해 주세요.");
            }}
          />
        </ReactCrop>
      </div>

      {error && (
        <p role="alert" className="mx-5 mt-4 rounded-md bg-caution-bg px-4 py-3 text-[13px] font-semibold text-caution-deep">
          {error}
        </p>
      )}

      <div className="flex flex-wrap justify-end gap-2 px-5 py-4">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="press rounded-md bg-low-bg px-4 py-2.5 text-[14px] font-bold text-sub"
        >
          취소
        </button>
        <button
          type="button"
          onClick={() => imageRef.current && finish(fullImageCrop(imageRef.current))}
          disabled={busy || !imageReady}
          className="press rounded-md border border-line px-4 py-2.5 text-[14px] font-bold text-sub"
        >
          전체 이미지 사용
        </button>
        <button
          type="button"
          onClick={() => completed && finish(completed)}
          disabled={busy || !completed}
          className="press rounded-md bg-blue-dark px-4 py-2.5 text-[14px] font-bold text-white disabled:bg-disabled"
        >
          {busy ? "편집 중" : "선택 영역 사용"}
        </button>
      </div>
    </dialog>
  );
}
