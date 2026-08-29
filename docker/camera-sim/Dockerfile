# Course project — no physical cameras yet (see docs/21_CAMERA_MANAGER.md
# and docker-compose.yml's "camera-sim" block). Builds the small runner
# that polls the camera-sim MinIO bucket's index and keeps one ffmpeg RTSP
# loop per camera in sync with whatever was last uploaded via
# POST /cameras/{id}/simulated-stream. Safe to delete this whole
# directory (and the docker-compose "camera-sim-runner"/"rtsp-sim"
# services) once real cameras are wired in.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY run.py /app/run.py

CMD ["python3", "/app/run.py"]
