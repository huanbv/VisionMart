"""VisionMart backend package."""

# Must match the root VERSION file (single source of truth for the whole
# project, see docs/44_VERSIONING.md) -- this literal exists because
# backend/ is built from its own Docker build context (./backend), which
# does not have access to the repo-root VERSION file at image build time.
# Bump both together when cutting a release.
__version__ = "1.0.0-rc1"
