#!/usr/bin/env python3
"""ArPDF — does Arabic survive a PDF?

Author: Syamjith NK
Third in the "Arabic breaks silently" series, after speech and screen rendering.

A PDF looks right and is therefore trusted. But almost nothing that CONSUMES a PDF
looks at it: procurement portals parse the text, search engines index it, ATS systems
read CVs, compliance tools scan for terms. All of them extract, and extraction is where
Arabic goes wrong - silently, because the page still looks perfect to a human.

This matters commercially in this region. A tender response submitted as a PDF whose
Arabic extracts as reversed or unjoined text is, to the system reading it, gibberish.

METHOD
------
Same round trip as the speech benchmark: write a known Arabic string into a PDF by each
common route, extract it back with each common extractor, and compare against the source.

Comparison is on the CHARACTER MULTISET after stripping diacritics and presentation
forms, so a reversed string still counts as "characters present" while a mangled one
does not - that separates the two failure modes instead of scoring both as simply wrong:

    order_ok       the characters come back in the original logical order
    chars_ok       all the characters are there, whatever the order
"""
import json
import subprocess
import tempfile
import unicodedata
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)

CASES = [
    ("greeting",   "مرحبا بكم في دولة الإمارات"),
    ("tender",     "التزامنا بالنزاهة والشفافية"),
    ("with_digits","في عام 2026 بلغت النسبة 47 بالمئة"),
    ("mixed",      "شركة Pixelogik للإنتاج الإعلامي"),
    ("name",       "سعادة نجيب المسكري"),
]


def normalise(s: str) -> str:
    """Strip diacritics and fold Arabic presentation forms back to base letters.

    Extractors often return the PRESENTATION form (the shaped glyph, U+FE70..U+FEFF)
    rather than the base letter. That is not a corruption - it is the same letter - so
    folding it is what makes the comparison measure the thing we care about.
    """
    s = unicodedata.normalize("NFKC", s)
    return "".join(c for c in s if not unicodedata.combining(c) and not c.isspace())


def make_pdf_chrome(text: str, out: Path) -> bool:
    """The route we actually use: HTML -> Chrome headless -> PDF."""
    html = f"""<!doctype html><meta charset="utf-8">
<style>body{{font-family:"SF Arabic","Geeza Pro",serif;font-size:28px;direction:rtl}}</style>
<p>{text}</p>"""
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "t.html"; h.write_text(html, encoding="utf-8")
        r = subprocess.run([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={out}", f"file://{h}"],
            capture_output=True, timeout=120)
        return out.exists() and out.stat().st_size > 0



def make_pdf_reportlab(text: str, out: Path, reshape: bool) -> bool:
    """ReportLab - the most common way software GENERATES a PDF rather than prints one.

    It does no complex-text layout, so it is the case where the arabic_reshaper recipe
    is genuinely required (see the ArShape result). Both variants are tested, because
    the naive one is what a developer writes first.
    """
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    try:
        pdfmetrics.registerFont(TTFont("ar", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
    except Exception:
        pdfmetrics.registerFont(TTFont("ar", "/Library/Fonts/Arial Unicode.ttf"))
    s = text
    if reshape:
        import arabic_reshaper
        from bidi.algorithm import get_display
        s = get_display(arabic_reshaper.reshape(text))
    c = canvas.Canvas(str(out))
    c.setFont("ar", 22)
    c.drawString(60, 700, s)
    c.save()
    return out.exists() and out.stat().st_size > 0



SOFFICE = "/Applications/LibreOffice.app/Contents/MacOS/soffice"


def make_pdf_libreoffice(text: str, out: Path) -> bool:
    """.docx -> LibreOffice -> PDF.

    This is the route that matters most and was the biggest gap in the first run: it is
    how document pipelines convert Word files server-side, and tender and legal documents
    are authored in Word. LibreOffice is not Microsoft Word - it is a different engine -
    but it IS the dominant headless converter, so it is the realistic path a .docx takes
    on its way to a portal.
    """
    src = HERE / "docx" / f"{out.stem.split('__')[0]}.docx"
    if not src.exists():
        return False
    subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir",
                    str(out.parent), str(src)], capture_output=True, timeout=180)
    made = out.parent / f"{src.stem}.pdf"
    if made.exists():
        made.replace(out)
    return out.exists() and out.stat().st_size > 0

GENERATORS = {
    "chrome (HTML->PDF)": lambda t, o: make_pdf_chrome(t, o),
    "reportlab (naive)": lambda t, o: make_pdf_reportlab(t, o, reshape=False),
    "reportlab (+reshaper)": lambda t, o: make_pdf_reportlab(t, o, reshape=True),
    "libreoffice (.docx)": lambda t, o: make_pdf_libreoffice(t, o),
}

EXTRACTORS = {}


def _pypdf(p: Path) -> str:
    from pypdf import PdfReader
    return " ".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)


def _pdfminer(p: Path) -> str:
    from pdfminer.high_level import extract_text
    return extract_text(str(p)) or ""


def _poppler(p: Path) -> str:
    r = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True, timeout=60)
    return r.stdout or ""


EXTRACTORS["pypdf"] = _pypdf
EXTRACTORS["pdfminer.six"] = _pdfminer
EXTRACTORS["poppler pdftotext"] = _poppler


if __name__ == "__main__":
    rows = []
    for cid, text in CASES:
      for gname, gfn in GENERATORS.items():
        slug = gname.split()[0] + ("_reshaped" if "reshaper" in gname else "")
        pdf = OUT / f"{cid}__{slug}.pdf"
        if not pdf.exists():
            try:
                if not gfn(text, pdf):
                    print(f"  {cid}/{gname}: generation FAILED"); continue
            except Exception as e:
                print(f"  {cid}/{gname}: {type(e).__name__} {e}"); continue
        want = normalise(text)
        for name, fn in EXTRACTORS.items():
            try:
                got_raw = fn(pdf)
            except Exception as e:
                rows.append({"case": cid, "generator": gname, "extractor": name, "error": str(e)[:60]}); continue
            got = normalise(got_raw)
            order_ok = want in got
            chars_ok = sorted(want) == sorted("".join(c for c in got if c in set(want)))
            rows.append({
                "case": cid, "text": text, "generator": gname, "extractor": name,
                "extracted": got_raw.strip()[:90],
                "order_ok": order_ok, "chars_ok": chars_ok,
                # Three distinct modes, not one. Calling them all "wrong" hid that
                # they need different fixes and have different blast radii.
                "verdict": (
                    "clean" if order_ok else
                    # whole string comes back in visual order = read backwards
                    "reversed" if normalise(text)[::-1] in got else
                    # the lam-alef ligature (لا) is one glyph in the PDF and comes
                    # back as two letters in the wrong order: الإمارات -> اإلمارات.
                    # Subtle enough to survive a human proofread.
                    "ligature" if chars_ok else
                    # letters intact but word/number boundaries lost: النسبة2026في
                    "spacing" if set(normalise(text)) <= set(got) else "mangled"),
            })
    (HERE / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    print(f"\nclean extractions out of {len(CASES)} strings\n")
    print(f"{'generator':24}" + "".join(f"{e:>20}" for e in EXTRACTORS))
    for g in GENERATORS:
        line = f"{g:24}"
        for e in EXTRACTORS:
            sub = [r for r in rows if r.get("generator") == g and r.get("extractor") == e and "verdict" in r]
            line += f"{sum(1 for r in sub if r['verdict']=='clean')}/{len(sub)}".rjust(20)
        print(line)
    print("\nfailure modes seen:")
    for v in ("reversed", "ligature", "spacing", "mangled"):
        n = sum(1 for r in rows if r.get("verdict") == v)
        if n: print(f"  {v:10} {n}")
