"""Camera simulation runner (course project — no physical cameras yet).

Polls the camera-sim MinIO bucket's small JSON index
(http://<MINIO_HOST>/<bucket>/_index.json, written by
CameraSimStorage.upload_video() in the backend) and keeps one `ffmpeg
-stream_loop -1` process per camera in sync with it: starts a loop the
first time a camera gets a video, restarts it if the video is replaced
(re-upload), and restarts it if it dies on its own (transient hiccup).

Deliberately dependency-free (stdlib only) so the image stays a thin
`python:3.11-slim` + `ffmpeg` layer. See docs/21_CAMERA_MANAGER.md and
docker-compose.yml's "camera-sim" block for the full design. Safe to
delete this whole file (and the "camera-sim-runner"/"rtsp-sim" services)
once real cameras are wired in — nothing else in the stack depends on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

MINIO_HOST = os.environ.get("MINIO_HOST", "minio:9000")
BUCKET = os.environ.get("MINIO_CAMERA_SIM_BUCKET", "camera-sim")
RTSP_HOST = os.environ.get("CAMERA_SIM_RTSP_HOST", "rtsp-sim")
RTSP_PORT = os.environ.get("CAMERA_SIM_RTSP_PORT", "8554")
POLL_SECONDS = float(os.environ.get("CAMERA_SIM_POLL_SECONDS", "10"))

INDEX_URL = f"http://{MINIO_HOST}/{BUCKET}/_index.json"

processes: dict[str, subprocess.Popen] = {}
last_seen: dict[str, float] = {}


def log(msg: str) -> None:
    print(f"[camera-sim] {msg}", flush=True)


def fetch_index() -> dict:
    try:
        with urllib.request.urlopen(INDEX_URL, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        # Expected until the first video is ever uploaded (object 404s) or
        # while MinIO is still starting up — not worth alarming about.
        log(f"index not available yet ({exc})")
        return {}


def stop_loop(camera_id: str) -> None:
    proc = processes.pop(camera_id, None)
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def start_loop(camera_id: str, key: str) -> subprocess.Popen:
    video_url = f"http://{MINIO_HOST}/{BUCKET}/{key}"
    rtsp_url = f"rtsp://{RTSP_HOST}:{RTSP_PORT}/cam-{camera_id}"
    log(f"starting loop for camera {camera_id}: {video_url} -> {rtsp_url}")
    # Tái mã hoá thay vì "-c copy", và đây là điểm quyết định chất lượng
    # hình. "-c copy" giữ nguyên khoảng keyframe của video gốc — video quay
    # điện thoại/camera dân dụng thường 2-10 GIÂY mới có một keyframe.
    # Trong khi đó phía đọc (ai-engine capture.py) mở một kết nối MỚI cho
    # mỗi lần lấy khung, tức gần như luôn nhảy vào giữa GOP: bộ giải mã
    # không có keyframe để bám nên trả ra màn xám loang cho tới keyframe
    # kế tiếp — đúng hiện tượng đã thấy trên live view.
    #
    # -g 25 (~1 giây/keyframe) khiến mọi lần nối vào luồng có điểm bám gần
    # như tức thì. ultrafast + giới hạn 1280w để 4 luồng không nuốt CPU của
    # VPS (video 4K mà tái mã hoá nguyên cỡ sẽ rất nặng). -an bỏ audio —
    # không ai dùng và đỡ một track có thể gây lỗi muxer.
    return subprocess.Popen(
        [
            "ffmpeg",
            "-loglevel", "warning",
            "-re",
            "-stream_loop", "-1",
            "-i", video_url,
            "-an",
            "-vf", "scale='min(1280,iw)':-2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-g", "10",
            "-keyint_min", "10",
            "-sc_threshold", "0",
            "-pix_fmt", "yuv420p",
            "-b:v", "4000k",
            "-maxrate", "5000k",
            "-bufsize", "8000k",
            # genpts: khi -stream_loop quay vòng, timestamp của vòng mới
            # phải được sinh lại, nếu không decoder phía sau vấp mốc thời
            # gian thụt lùi và vỡ hình đúng lúc video lặp.
            "-fflags", "+genpts",
            # TCP thay vì UDP mặc định: rớt gói UDP là nguồn của các vệt
            # nhòe kéo theo chuyển động.
            "-rtsp_transport", "tcp",
            "-f", "rtsp",
            rtsp_url,
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def main() -> None:
    log(f"runner starting, polling {INDEX_URL} every {POLL_SECONDS}s")
    while True:
        index = fetch_index()

        # (Re)start loops for cameras that are new or whose video changed.
        for camera_id, meta in index.items():
            key = meta.get("key")
            updated_at = meta.get("updated_at")
            if not key:
                continue
            if last_seen.get(camera_id) != updated_at:
                stop_loop(camera_id)
                processes[camera_id] = start_loop(camera_id, key)
                last_seen[camera_id] = updated_at

        # Restart any loop that exited on its own (network hiccup, MinIO
        # restart, etc.) — as long as it's still listed in the index.
        for camera_id, proc in list(processes.items()):
            if proc.poll() is not None and camera_id in index:
                key = index[camera_id].get("key")
                if key:
                    log(
                        f"loop for camera {camera_id} exited "
                        f"(code {proc.returncode}), restarting"
                    )
                    processes[camera_id] = start_loop(camera_id, key)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
