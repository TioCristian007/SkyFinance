"""Convierte docs/SECURITY_INFRASTRUCTURE.md a PDF usando Chrome headless."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "SECURITY_INFRASTRUCTURE.md"
HTML = ROOT / "docs" / "SECURITY_INFRASTRUCTURE.html"
PDF = ROOT / "docs" / "SECURITY_INFRASTRUCTURE.pdf"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body {
  font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
  color: #1a1a1a;
  max-width: 100%;
  margin: 0;
}
h1, h2, h3, h4 {
  color: #0D1B2A;
  font-weight: 600;
  page-break-after: avoid;
}
h1 { font-size: 22pt; border-bottom: 3px solid #00C853; padding-bottom: 6px; margin-top: 0; }
h2 { font-size: 15pt; margin-top: 22pt; border-bottom: 1px solid #d0d7de; padding-bottom: 4px; }
h3 { font-size: 12.5pt; margin-top: 16pt; }
h4 { font-size: 11pt; margin-top: 12pt; }
p, li { orphans: 2; widows: 2; }
blockquote {
  border-left: 4px solid #00C853;
  background: #f6fbf7;
  margin: 8pt 0;
  padding: 6pt 10pt;
  color: #2c3e50;
}
code {
  font-family: 'Cascadia Code', 'Consolas', 'Monaco', monospace;
  font-size: 9.5pt;
  background: #f1f3f5;
  padding: 1px 5px;
  border-radius: 3px;
  color: #d6336c;
}
pre {
  background: #0D1B2A;
  color: #e6edf3;
  padding: 10pt 12pt;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 9pt;
  line-height: 1.4;
  page-break-inside: avoid;
}
pre code { background: transparent; color: inherit; padding: 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8pt 0;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #d0d7de;
  padding: 5pt 8pt;
  text-align: left;
  vertical-align: top;
}
th {
  background: #0D1B2A;
  color: #fff;
  font-weight: 600;
}
tr:nth-child(even) td { background: #f9fafb; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #d0d7de; margin: 18pt 0; }
ul, ol { padding-left: 22pt; }
li { margin: 2pt 0; }
strong { color: #0D1B2A; }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8" />
<title>Sky Finanzas — Infraestructura y Ciberseguridad</title>
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>
"""


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    raise SystemExit("No encontré Chrome ni Edge instalado.")


def main() -> int:
    md_text = SRC.read_text(encoding="utf-8")
    body = markdown.markdown(
        md_text,
        extensions=["extra", "tables", "fenced_code", "toc", "sane_lists"],
        output_format="html5",
    )
    HTML.write_text(HTML_TEMPLATE.format(css=CSS, body=body), encoding="utf-8")

    chrome = find_chrome()
    src_url = HTML.resolve().as_uri()
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={PDF}",
        "--no-margins",
        src_url,
    ]
    print("Ejecutando:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
        return result.returncode

    if not PDF.exists():
        print("Chrome terminó sin error pero el PDF no apareció.")
        return 1

    size = PDF.stat().st_size
    print(f"OK: {PDF} ({size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
