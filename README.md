---
license: cc-by-4.0
language:
  - ar
task_categories:
  - text-classification
tags:
  - arabic
  - pdf
  - text-extraction
  - document-understanding
  - evaluation
  - internationalization
pretty_name: ArPDF
size_categories:
  - n<1K
configs:
  - config_name: results
    data_files:
      - split: test
        path: results.jsonl
---

# ArPDF — does Arabic survive a PDF?

**Author:** Syamjith NK
**Write-up:** [Your Arabic PDF is fine. What reads it is not.](https://syamjithnk.com/arabic-pdf-extraction)
Third in a series with [ArNum-TTS](https://huggingface.co/datasets/syamjithnk/arnum-tts)
(speech) and [ArShape](https://huggingface.co/datasets/syamjithnk/arshape) (screen rendering).

## The finding

**No PDF generator and extractor pair reads Arabic reliably, and correctness depends on
the pair rather than on either tool.**

5 Arabic strings × 4 generators × 3 extractors. Clean extractions out of 5:

| generator | pypdf | pdfminer.six | poppler pdftotext |
|---|---|---|---|
| Chrome (HTML → PDF) | 3/5 | **0/5** | 1/5 |
| ReportLab (naive) | **0/5** | **5/5** | **0/5** |
| ReportLab (+ reshaper) | 3/5 | **0/5** | 3/5 |
| LibreOffice (.docx → PDF) | **5/5** | **0/5** | 2/5 |

## Why pdfminer inverts

pdfminer is 0/5 against three generators and 5/5 against exactly one — the only one that
performs no text layout. That is not a coincidence, and it explains the whole table.

ReportLab-naive writes the characters into the PDF in **logical** order, because it does
no shaping or bidi. Chrome, LibreOffice and reshaped ReportLab all lay the line out
visually first, so the PDF stores glyphs in **visual** order. pdfminer returns what is
stored without re-applying bidi, so it is right precisely when the generator was naive.
pypdf and poppler apply their own reordering heuristics, which is why they land in
between.

So the question a PDF answers is not "is the Arabic correct" but "which order is it
stored in, and does this reader re-apply bidi". No tool tells you either.

The two ends invert. ReportLab-naive extracts perfectly through pdfminer and fails every
other reader; Chrome — the route most web tooling uses — is **0 for 5** through pdfminer,
which is what many document pipelines run.

So you cannot choose a "good" PDF library or a "good" extractor. A document that survives
one reader is unreadable to the next, and when you submit a PDF you do not control which
reader is on the other side.

## Why it matters

A PDF *looks* correct, so it is trusted. But almost nothing that consumes one looks at
it — procurement portals parse the text, search engines index it, compliance tools scan
for terms, applicant systems read CVs. All of them extract.

An Arabic tender response that renders perfectly on screen and extracts as reversed text
is, to the system reading it, gibberish. Nobody involved sees the failure.

## Three distinct failure modes

Counted separately, because they need different fixes and have very different blast radii.

| mode | what happens | example |
|---|---|---|
| reversed | the whole string comes back in visual order, so it reads backwards | source `مرحبا بكم في دولة الإمارات` |
| | | extracted `تاراملإا ةلود يف مكب ابحرم` |
| ligature | the lam-alef (لا) is one glyph in the PDF and returns as two letters in the wrong order | source `الإمارات` |
| | | extracted `اإلمارات` |
| spacing | letters intact, word and number boundaries lost | extracted `النسبة2026في` |

Observed across the 60-row matrix: **22 clean, 23 ligature, 11 reversed, 4 mangled**.

> **Correction, 21 August 2026.** This line previously read *"9 reversed, 17 ligature, 4
> mangled"*. Those figures were wrong: they summed to 30 rows when the matrix has 38
> non-clean results, and they under-counted both reversed and ligature. The corrected counts
> above are recomputed directly from `results.jsonl` and can be reproduced with:
>
> ```python
> import json, collections
> collections.Counter(json.loads(l)["verdict"] for l in open("results.jsonl"))
> ```
>
> The direction of the finding is unchanged — ligature remains the most common failure mode
> and the most dangerous, because it survives a human proofread. Only the counts were wrong.

**The ligature mode is the dangerous one.** It is subtle enough to survive a human
proofread — a reader skims past `اإلمارات` — while still breaking exact-match search,
keyword compliance checks and any automated comparison.

## What this does NOT cover

Stated plainly, because it is the obvious next question:

- **Microsoft Word itself, InDesign and LaTeX are untested.** LibreOffice covers the
  .docx route because it is the dominant headless converter, but it is a different engine
  from Word and may lay text out differently. InDesign and LaTeX are not installed here,
  and WeasyPrint could not run (it needs Pango).
- One font (system Arabic) and one page layout. Embedded subsets and CID fonts may behave
  differently.
- Extraction only. It says nothing about whether the PDF *renders* correctly — it does.

## Reproduce

```sh
python pdf_bench.py
```

Writes every generator × extractor combination to `results.jsonl` with the extracted text
for each, so the failure modes can be inspected rather than taken on trust.
