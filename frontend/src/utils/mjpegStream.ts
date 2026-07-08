/**
 * Hand-rolled client for the backend's continuous MJPEG live-view stream
 * (`GET /cameras/{id}/live`, media type `multipart/x-mixed-replace;
 * boundary=frame`).
 *
 * Why not just `<img src="/api/v1/cameras/{id}/live">`? Every route in
 * this app is JWT-bearer-authenticated (see api/client.ts), and an
 * `<img>` tag has no way to attach a custom `Authorization` header to
 * its request. So instead we `fetch()` the endpoint ourselves (which can
 * carry the header), read the response body as a stream, and manually
 * split it on the `--frame` multipart boundary to pull out each JPEG —
 * then hand the caller an object URL per frame, the same way an `<img>`
 * would consume one, one at a time.
 */

import { tokenStore } from "@/api/client";

const BOUNDARY = "--frame";
const HEADER_END = "\r\n\r\n";

export interface MjpegStreamHandle {
  /** Stop the stream, abort the in-flight fetch, and release the last frame's object URL. */
  stop: () => void;
}

function indexOfBytes(haystack: Uint8Array, needle: Uint8Array, from = 0): number {
  outer: for (let i = from; i <= haystack.length - needle.length; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

/**
 * Opens the live MJPEG stream for a camera. Calls `onFrame` with a fresh
 * object URL each time a full JPEG frame has been parsed out of the
 * stream (the previous frame's URL is revoked automatically — the
 * caller doesn't need to track or clean these up). Calls `onError` at
 * most once, on stream failure (auth error, camera has no stream_url,
 * network drop, etc).
 *
 * Returns a handle whose `stop()` aborts the underlying fetch and
 * revokes the last outstanding object URL. Always call `stop()` when
 * the viewer closes (e.g. in a modal's onClose / a component's cleanup
 * effect) — otherwise the connection (and the ai-engine's
 * cv2.VideoCapture behind it) stays open indefinitely.
 */
export function openMjpegStream(
  cameraId: string,
  onFrame: (objectUrl: string) => void,
  onError: (message: string) => void,
): MjpegStreamHandle {
  const controller = new AbortController();
  let stopped = false;
  let lastUrl: string | null = null;

  const baseURL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "/api/v1";
  const url = `${baseURL}/cameras/${cameraId}/live`;
  const token = tokenStore.getAccess();

  const revokeLast = () => {
    if (lastUrl) {
      URL.revokeObjectURL(lastUrl);
      lastUrl = null;
    }
  };

  const publish = (bytes: Uint8Array) => {
    revokeLast();
    const blob = new Blob([bytes], { type: "image/jpeg" });
    const objectUrl = URL.createObjectURL(blob);
    lastUrl = objectUrl;
    onFrame(objectUrl);
  };

  (async () => {
    try {
      if (!token) {
        onError("Chưa đăng nhập");
        return;
      }
      const resp = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        onError(`Không thể mở luồng trực tiếp (HTTP ${resp.status})`);
        return;
      }

      const reader = resp.body.getReader();
      let buffer = new Uint8Array(0);
      const encoder = new TextEncoder();
      const boundaryBytes = encoder.encode(BOUNDARY);
      const headerEndBytes = encoder.encode(HEADER_END);
      const decoder = new TextDecoder();

      while (!stopped) {
        const { done, value } = await reader.read();
        if (done) break;
        if (!value || value.length === 0) continue;

        // Append the newly-read chunk onto whatever partial frame we
        // were still holding.
        const merged = new Uint8Array(buffer.length + value.length);
        merged.set(buffer, 0);
        merged.set(value, buffer.length);
        buffer = merged;

        // Drain as many complete frames as the buffer currently holds
        // -- a single read() can contain more than one frame.
        for (;;) {
          const boundaryIdx = indexOfBytes(buffer, boundaryBytes);
          if (boundaryIdx === -1) break;

          const headerStart = boundaryIdx + boundaryBytes.length;
          const headerEndIdx = indexOfBytes(buffer, headerEndBytes, headerStart);
          if (headerEndIdx === -1) break; // header not fully arrived yet

          const headerText = decoder.decode(
            buffer.slice(headerStart, headerEndIdx),
          );
          const lengthMatch = /Content-Length:\s*(\d+)/i.exec(headerText);
          if (!lengthMatch) {
            // Malformed part -- drop up to (and including) this boundary
            // and keep scanning instead of getting stuck forever.
            buffer = buffer.slice(headerEndIdx + headerEndBytes.length);
            continue;
          }
          const frameLength = Number(lengthMatch[1]);
          const frameStart = headerEndIdx + headerEndBytes.length;
          const frameEnd = frameStart + frameLength;
          if (buffer.length < frameEnd) break; // frame body not fully arrived yet

          const frameBytes = buffer.slice(frameStart, frameEnd);
          publish(frameBytes);

          // Leave the trailing \r\n before the next boundary in place;
          // the next loop iteration's indexOfBytes search just skips
          // past it when it finds the next "--frame".
          buffer = buffer.slice(frameEnd);
        }

        // Avoid unbounded growth if we somehow never find a boundary
        // (e.g. a non-MJPEG response slipped through).
        if (buffer.length > 20 * 1024 * 1024) {
          onError("Luồng dữ liệu không hợp lệ");
          return;
        }
      }
    } catch (err) {
      if (stopped || controller.signal.aborted) return; // expected on stop()
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Mất kết nối luồng trực tiếp: ${msg}`);
    }
  })();

  return {
    stop: () => {
      if (stopped) return;
      stopped = true;
      controller.abort();
      revokeLast();
    },
  };
}
