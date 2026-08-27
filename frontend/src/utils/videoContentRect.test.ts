import { describe, expect, it } from "vitest";

import { mapNormToContent, videoContentRect } from "./videoContentRect";

describe("videoContentRect", () => {
  it("pillarboxes a 16:9 frame in a wider element (max-height cap)", () => {
    const rect = videoContentRect(1000, 480, 1920, 1080);
    expect(rect.y).toBe(0);
    expect(rect.h).toBe(480);
    expect(rect.w).toBeCloseTo(480 * (1920 / 1080), 5);
    expect(rect.x).toBeCloseTo((1000 - rect.w) / 2, 5);
  });

  it("letterboxes a 16:9 frame in a taller element", () => {
    const rect = videoContentRect(640, 480, 1920, 1080);
    expect(rect.x).toBe(0);
    expect(rect.w).toBe(640);
    expect(rect.h).toBeCloseTo(640 / (1920 / 1080), 5);
    expect(rect.y).toBeCloseTo((480 - rect.h) / 2, 5);
  });

  it("fills the element when ratios match", () => {
    const rect = videoContentRect(1280, 720, 1920, 1080);
    expect(rect).toEqual({ x: 0, y: 0, w: 1280, h: 720 });
  });

  it("maps saved ROI fractions onto the painted frame, not the black bars", () => {
    const rect = videoContentRect(1000, 480, 1920, 1080);
    const left = mapNormToContent(0, 0.5, rect);
    expect(left.x).toBeCloseTo(rect.x, 5);
    expect(left.x).toBeGreaterThan(0);
  });
});
