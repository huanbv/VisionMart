"""Process entrypoint - used by `python main.py` for local debugging.

Production launches via:
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import uvicorn

from app.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.BACKEND_HOST,
        port=settings.BACKEND_PORT,
        reload=settings.APP_DEBUG,
    )


if __name__ == "__main__":
    main()
