"""Maya's Monday competitor deck: one pipeline, fed by the web (live) or by a file (tests)."""

__version__ = "0.1.0"

BUILT_FOR = "maya"


def write_text(path, text: str) -> None:
    """Write UTF-8 with \\n line endings on every OS (Path.write_text(newline=) is 3.10+)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
