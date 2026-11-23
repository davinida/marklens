// 견고성·보안 점검(2026-11-23, docs/MarkLens_견고성_보안_점검.md)에서 찾은 화면 쪽 항목의 회귀 시험.
// 지금 고쳐지지 않은 항목은 it.fails 로 두고 이름에 점검 문서의 항목 번호를 적는다(고치면 실패로 바뀌어
// it.fails 를 지우라고 알린다).
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PixelCrop } from "react-image-crop";
import { cropImageFile } from "@/lib/crop";

interface FakeCanvas {
  width: number;
  height: number;
  getContext: () => unknown;
  toBlob: (callback: (blob: Blob | null) => void) => void;
}

function fakeCanvas(): FakeCanvas {
  const canvas: FakeCanvas = {
    width: 0,
    height: 0,
    getContext: () => ({ drawImage: () => undefined, imageSmoothingEnabled: true, imageSmoothingQuality: "high" }),
    toBlob: (callback) => callback(new Blob([new Uint8Array(64)], { type: "image/webp" })),
  };
  return canvas;
}

function image(width: number, height: number): HTMLImageElement {
  return { width, height, naturalWidth: width, naturalHeight: height } as HTMLImageElement;
}

const crop = (width: number, height: number): PixelCrop => ({ unit: "px", x: 0, y: 0, width, height });

describe("자르기 결과 치수(crop.ts)", () => {
  let created: FakeCanvas[] = [];
  const original = document.createElement.bind(document);

  function mockCanvas() {
    created = [];
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      if (tag !== "canvas") return original(tag);
      const canvas = fakeCanvas();
      created.push(canvas);
      return canvas as unknown as HTMLCanvasElement;
    }) as typeof document.createElement);
  }

  afterEach(() => vi.restoreAllMocks());

  it("보통 로고는 2048 이하로 줄이되 비율을 지킨다(지금 동작)", async () => {
    mockCanvas();
    await cropImageFile(image(4000, 3000), crop(4000, 3000), "logo.png");
    expect(created[0].width).toBe(2048);
    expect(created[0].height).toBe(1536);
  });

  it.fails("R-P1-4: 가늘고 긴 4000×32 를 줄여도 짧은 변이 서버 최소 32px 아래로 내려가지 않는다", async () => {
    mockCanvas();
    await cropImageFile(image(4000, 32), crop(4000, 32), "thin.png");
    expect(Math.min(created[0].width, created[0].height)).toBeGreaterThanOrEqual(32);
  });
});
