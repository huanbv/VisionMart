/**
 * Where the decoded video actually paints inside an <video> element.
 *
 * Native players (and `object-fit: contain`) letterbox / pillarbox when the
 * element's box is wider or taller than the frame. Overlay math that uses
 * clientWidth × clientHeight therefore stretches saved ROI (0–1 of the
 * frame) into the black bars.
 */

export type ContentRect = { x: number; y: number; w: number; h: number };

export function videoContentRect(
  elW: number,
  elH: number,
  vidW: number,
  vidH: number,
): ContentRect {
  if (elW <= 0 || elH <= 0) return { x: 0, y: 0, w: 0, h: 0 };
  const fw = vidW > 0 ? vidW : elW;
  const fh = vidH > 0 ? vidH : elH;
  const elRatio = elW / elH;
  const vidRatio = fw / fh;
  if (vidRatio > elRatio) {
    const h = elW / vidRatio;
    return { x: 0, y: (elH - h) / 2, w: elW, h };
  }
  const w = elH * vidRatio;
  return { x: (elW - w) / 2, y: 0, w, h: elH };
}

export function mapNormToContent(
  nx: number,
  ny: number,
  rect: ContentRect,
): { x: number; y: number } {
  return { x: rect.x + nx * rect.w, y: rect.y + ny * rect.h };
}

export function mapPixelToContent(
  px: number,
  py: number,
  vidW: number,
  vidH: number,
  rect: ContentRect,
): { x: number; y: number } {
  const fw = vidW > 0 ? vidW : 1;
  const fh = vidH > 0 ? vidH : 1;
  return {
    x: rect.x + (px / fw) * rect.w,
    y: rect.y + (py / fh) * rect.h,
  };
}
