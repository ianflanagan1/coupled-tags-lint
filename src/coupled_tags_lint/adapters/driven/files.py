"""Reading files from the local disk."""

from typing import final


@final
class LocalFiles:
    def read(self, path: str) -> str | None:
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None
