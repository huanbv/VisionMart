# VisionMart Evaluation Framework -- one-off baseline/report generator.
#
# Standalone image, independent of backend/ai-engine's (much heavier,
# torch-carrying) images -- see docs/EVALUATION_FRAMEWORK.md. The
# documented baseline/smoke-test command (`evaluate --synthetic-frames N`)
# only needs numpy/opencv/pandas/matplotlib to produce a report; it never
# imports torch or ultralytics. A `--with-yolo` run against real footage
# is expected to run somewhere that has those (the ai-engine
# container/VPS), not from this image.
FROM python:3.11-slim

WORKDIR /app

COPY evaluation/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY evaluation /app/evaluation

# evaluation/cli.py's `evaluate` command runs every frame through the
# ai-engine's OpenCV preprocessing pipeline (`app.vision.pipeline.
# preprocess_for_detection`) BEFORE it ever gets near YOLO -- that call
# is unconditional, not gated behind --with-yolo, so it's needed even
# for the plain `--synthetic-frames` smoke test. cli.py resolves it via
# `sys.path.insert(0, <repo-root>/ai-engine)`, so it must land at
# exactly /app/ai-engine/app inside this image (a sibling of
# /app/evaluation, matching the repo's own evaluation/ + ai-engine/
# layout). Only app.vision.* is ever actually imported from this tree,
# and that subpackage only needs numpy/opencv/PyYAML (all already in
# requirements.txt) -- copying the rest of ai-engine/app alongside it is
# harmless (unimported code, no extra deps) and keeps this COPY simple.
COPY ai-engine/app /app/ai-engine/app

ENTRYPOINT ["python", "-m", "evaluation.cli"]
CMD ["evaluate", "--synthetic-frames", "40", "--output-dir", "/app/evaluation_results"]
