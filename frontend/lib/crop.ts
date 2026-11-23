import type { PixelCrop } from "react-image-crop";

const MAX_OUTPUT_DIMENSION = 2048;
// 서버가 받는 최소 치수(계약 v2 §5-1, backend config.MIN_IMAGE_DIM) — 축소해도 짧은 변이 이 아래로 가지 않게
const MIN_OUTPUT_DIMENSION = 32;
const MAX_OUTPUT_BYTES = 10 * 1024 * 1024;

function outputName(name: string): string {
  const stem = name.replace(/\.[^.]+$/, "").slice(0, 80) || "logo";
  return `${stem}-crop.webp`;
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => {
        if (blob) resolve(blob);
        else reject(new Error("이미지를 변환할 수 없어요."));
      },
      "image/webp",
      0.9,
    );
  });
}

export async function cropImageFile(
  image: HTMLImageElement,
  crop: PixelCrop,
  sourceName: string,
): Promise<File> {
  if (crop.width < 1 || crop.height < 1 || image.width < 1 || image.height < 1) {
    throw new Error("자를 영역을 선택해 주세요.");
  }

  const scaleX = image.naturalWidth / image.width;
  const scaleY = image.naturalHeight / image.height;
  const sourceWidth = Math.max(1, Math.round(crop.width * scaleX));
  const sourceHeight = Math.max(1, Math.round(crop.height * scaleY));
  if (sourceWidth < 32 || sourceHeight < 32) {
    throw new Error("자를 영역은 가로와 세로가 각각 32px 이상이어야 해요.");
  }

  // 긴 변을 2048 로 줄이되, 짧은 변이 서버 최소(32px) 아래로 내려가면 그만큼 덜 줄인다 — 원본이 서버
  // 허용 범위(32–4096)면 이 축소 때문에 거절되지 않는다(견고성 점검 R-P1-4: 4000×32 → 2048×16 → 400).
  const outputScale = Math.min(
    1,
    Math.max(
      MAX_OUTPUT_DIMENSION / Math.max(sourceWidth, sourceHeight),
      MIN_OUTPUT_DIMENSION / Math.min(sourceWidth, sourceHeight),
    ),
  );
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(sourceWidth * outputScale));
  canvas.height = Math.max(1, Math.round(sourceHeight * outputScale));

  const context = canvas.getContext("2d");
  if (!context) throw new Error("이미지 편집기를 시작할 수 없어요.");
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.drawImage(
    image,
    crop.x * scaleX,
    crop.y * scaleY,
    sourceWidth,
    sourceHeight,
    0,
    0,
    canvas.width,
    canvas.height,
  );

  const blob = await canvasBlob(canvas);
  if (blob.size > MAX_OUTPUT_BYTES) {
    throw new Error("편집한 이미지가 10MB를 넘어요. 더 작은 영역을 선택해 주세요.");
  }
  return new File([blob], outputName(sourceName), {
    type: "image/webp",
    lastModified: Date.now(),
  });
}

export function fullImageCrop(image: HTMLImageElement): PixelCrop {
  return {
    unit: "px",
    x: 0,
    y: 0,
    width: image.width,
    height: image.height,
  };
}

