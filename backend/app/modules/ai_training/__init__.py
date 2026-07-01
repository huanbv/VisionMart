"""AI training bounded context.

Handles uploading training images per product, spawning training jobs, and
tracking their status. The heavy lifting (dataset build + YOLO training) is
delegated to the ai-engine service via HTTP.
"""
