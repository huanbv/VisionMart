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

ENTRYPOINT ["python", "-m", "evaluation.cli"]
CMD ["evaluate", "--synthetic-frames", "40", "--output-dir", "/app/evaluation_results"]
