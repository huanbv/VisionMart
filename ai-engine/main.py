"""Process entrypoint for local debugging of the AI Engine."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=8100, reload=True)


if __name__ == "__main__":
    main()
