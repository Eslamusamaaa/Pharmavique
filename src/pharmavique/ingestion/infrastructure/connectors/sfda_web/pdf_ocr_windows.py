"""OCR for scanned PDFs with what Windows already has: nothing is installed, nothing leaves the PC.

Two of the project's PowerShell scripts do the work: `pdf_pages_windows.ps1` draws each page as a
picture and `ocr_windows.ps1` reads the pictures (English and Arabic engines). Pages are joined in
order. The text is OCR: it can hold misread characters, and callers mark it as such.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[6] / "scripts"
_RENDER = _SCRIPTS / "pdf_pages_windows.ps1"
_OCR = _SCRIPTS / "ocr_windows.ps1"


def _powershell(script: Path, *args: str) -> None:
    shell = shutil.which("powershell.exe")
    if shell is None:
        raise RuntimeError("the Windows OCR needs powershell.exe, which was not found")
    subprocess.run(  # noqa: S603 - fixed command, our own scripts, paths from our own files
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        check=True,
        capture_output=True,
    )


def windows_image_ocr(picture: Path) -> str | None:
    """The text of one picture (jpg, png), or None when Windows could not read the file."""
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "out.jsonl"
        _powershell(_OCR, "-Files", str(picture.resolve()), "-Out", str(out))
        lines = [ln for ln in out.read_text(encoding="utf-8-sig").splitlines() if ln.strip()]
        if not lines:
            return None
        item = json.loads(lines[0], strict=False)
        return None if item.get("error") else str(item["text"])


def windows_pdf_ocr(pdf: Path) -> str | None:
    """The text of every page of `pdf`, or None when a page could not be drawn or read."""
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        pages_out = work / "pages.jsonl"
        # the render script prints JSON lines; the OCR script writes to a file we read back
        shell = shutil.which("powershell.exe")
        if shell is None:
            raise RuntimeError("the Windows OCR needs powershell.exe, which was not found")
        rendered = subprocess.run(  # noqa: S603 - fixed command, our own script
            [
                shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(_RENDER),
                "-Files", str(pdf.resolve()), "-OutDir", str(work / "pages"),
            ],
            check=True,
            capture_output=True,
        )  # fmt: skip
        row = json.loads(rendered.stdout.decode("utf-8-sig").strip().splitlines()[-1])
        pages = [Path(p) for p in row["pages"]]
        if row.get("error") or not pages:
            return None
        listing = work / "pages.txt"
        listing.write_text("\n".join(str(p) for p in pages), encoding="utf-8")
        _powershell(_OCR, "-List", str(listing), "-Out", str(pages_out))
        found: dict[str, str | None] = {}
        for line in pages_out.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                item = json.loads(line, strict=False)
                found[str(Path(item["file"]).resolve())] = (
                    None if item.get("error") else item["text"]
                )
        texts = [found.get(str(p.resolve())) for p in pages]
        if any(t is None for t in texts):
            return None
        return "\n\n".join(t for t in texts if t)
