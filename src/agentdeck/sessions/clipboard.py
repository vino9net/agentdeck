"""Copy images to the system clipboard."""

import shutil
import subprocess
import sys

import structlog

logger = structlog.get_logger()


def copy_image_to_clipboard(path: str, fmt: str) -> None:
    """Copy an image file to the system clipboard.

    Args:
        path: Absolute path to the image file.
        fmt: MIME subtype — "png" or "jpeg".

    Raises:
        RuntimeError: If no clipboard tool is available
            or the copy command fails.
    """
    if sys.platform == "darwin":
        _copy_macos(path, fmt)
    else:
        _copy_linux(path, fmt)


def _copy_macos(path: str, fmt: str) -> None:
    """Copy image to clipboard on macOS via osascript."""
    if fmt == "jpeg":
        as_class = "JPEG picture"
    else:
        as_class = "«class PNGf»"

    script = f'set the clipboard to (read (POSIX file "{path}") as {as_class})'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        logger.error(
            "clipboard_macos_failed",
            stderr=result.stderr,
        )
        msg = f"osascript failed: {result.stderr}"
        raise RuntimeError(msg)


def _copy_linux(path: str, fmt: str) -> None:
    """Copy image to clipboard on Linux via xclip or wl-copy."""
    mime = f"image/{fmt}"

    if shutil.which("xclip"):
        cmd = [
            "xclip",
            "-selection",
            "clipboard",
            "-t",
            mime,
            "-i",
            path,
        ]
    elif shutil.which("wl-copy"):
        cmd = ["wl-copy", "--type", mime]
    else:
        msg = "No clipboard tool found (need xclip or wl-copy)"
        raise RuntimeError(msg)

    if "wl-copy" in cmd[0]:
        with open(path, "rb") as f:
            result = subprocess.run(
                cmd,
                stdin=f,
                capture_output=True,
                timeout=10,
            )
    else:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=10,
        )

    if result.returncode != 0:
        logger.error(
            "clipboard_linux_failed",
            stderr=result.stderr,
        )
        msg = f"Clipboard copy failed: {result.stderr}"
        raise RuntimeError(msg)
