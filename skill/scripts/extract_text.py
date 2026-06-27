#!/usr/bin/env python3
"""Extract plain text from a disaster document (PDF / DOCX / TXT) into a single .txt.

Usage:
    python extract_text.py <input> <output.txt>

PDF  -> uses `pdftotext` (poppler) if available, else falls back to pypdf.
DOCX -> unzips word/document.xml and strips tags.
TXT  -> copied through.
"""
import sys, os, re, html, subprocess, shutil, zipfile


def from_pdf(path, out):
    if shutil.which("pdftotext"):
        subprocess.run(["pdftotext", path, out], check=True)
        return
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader  # type: ignore
    r = PdfReader(path)
    with open(out, "w", encoding="utf-8") as g:
        for p in r.pages:
            g.write((p.extract_text() or "") + "\n")


def from_docx(path, out):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = xml.replace("</w:p>", "\n")
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    with open(out, "w", encoding="utf-8") as g:
        g.write(text)


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src, out = sys.argv[1], sys.argv[2]
    ext = os.path.splitext(src)[1].lower()
    if ext == ".pdf":
        from_pdf(src, out)
    elif ext == ".docx":
        from_docx(src, out)
    elif ext in (".txt", ".md"):
        shutil.copyfile(src, out)
    else:
        raise SystemExit(f"Unsupported extension: {ext} (use pdf/docx/txt)")
    n = sum(1 for _ in open(out, encoding="utf-8", errors="replace"))
    print(f"OK: {out} ({os.path.getsize(out)} bytes, {n} lines)")


if __name__ == "__main__":
    main()
