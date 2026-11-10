# Controlled editing, document handling

Edit in place. The default is a local textual correction inside the file the user supplied, not a regenerated document.

## What is preserved in every format

Headings, numbering and outline levels; page structure, section breaks, orientation and margins; tables, charts, images, captions, cross-references, fields, formulas, footnotes, endnotes, bookmarks, hyperlinks, headers and footers; styles; native objects; comments and tracked changes where they are part of the document's working state; metadata not directly affected by the edit, except where package and metadata hygiene expressly identifies unnecessary personal, local-path, temporary, add-in, AI-tool, web-extension or other non-deliverable metadata for removal. Legitimate project authorship, approvals, revision history, signatures, document-control data and other required provenance are preserved in every case. See `metadata-hygiene.md`.

Never convert a native table or chart into an image. Never flatten an editable object. Never restyle because another look would be better. Where a corrected sentence is shorter or longer than the original, that is the only change; surrounding layout is left alone.

## Where the text lives

The review covers every text run, not the body paragraphs alone:

- table cells and table headings
- chart titles, legends, axis labels, data labels
- figure captions and callouts
- dashboard and status labels
- text boxes and shapes
- headers and footers carrying substantive text
- footnotes, endnotes, comments
- alt text where a reader will encounter it

`scripts/extract_text.py` lists these locations with a reference for each passage: a paragraph index in Word, a slide or notes reference in PowerPoint, a sheet and cell reference in Excel, and the chart part for titles and cached labels.

The script is supplementary. It reads the common OOXML text parts and skips template scaffolding such as slide layouts and masters. It does not reach embedded objects, SmartArt, OLE or linked parts, or every third-party extension, and it deliberately skips numeric cell values and formula results, which are not wording. Do not treat a clean run as evidence that all reader-visible text was reviewed. The pre-issue scan is run against the document; the script only reduces what gets missed.

## Word (.docx)

A .docx is a zip of XML. Edit `word/document.xml` in place rather than rebuilding the file.

```bash
unzip -q in.docx -d unpacked/
find unpacked -type l -delete
# text is often split across runs; merge adjacent identically formatted runs first
# so a visible phrase exists as a contiguous string
# then edit unpacked/word/document.xml, and header*.xml / footer*.xml if needed
(cd unpacked && zip -XrqD ../out.docx . -x '.*')
```

Apply each correction as an exact string replacement and assert it matched exactly once. Do not reformat or pretty-print the XML. Charts live in `word/charts/`, footnotes in `word/footnotes.xml`, comments in `word/comments.xml`. After rebuilding, confirm the part count, paragraph count, table count and media count are unchanged except where an edit required otherwise.

## PowerPoint (.pptx) and Excel (.xlsx)

Same principle. Edit the slide, notes, chart, sharedStrings or sheet XML in place and rezip. In .xlsx, remember that most visible text sits in `xl/sharedStrings.xml`, and that editing a cell containing a formula result is not a text edit at all. Do not touch formulas, defined names, validation, conditional formats or pivot caches.

## PDF

A PDF is an output format, not a source. Do not attempt an in-place text edit. Metadata hygiene is a separate matter from text editing and still applies: inspect document properties and XMP metadata, and sanitize only where that changes no visible content and no document-control information. See `metadata-hygiene.md`. Ask for the source document. If only the PDF exists, deliver the corrections as a marked list of before and after wording with page and location, and say plainly that the file itself was not edited.

## Markdown, plain text, HTML, email

Edit the file directly. Keep the existing heading levels, list markers, code fences, front matter and link syntax. Do not renumber, re-indent or reflow lines that the correction does not touch.

## When no file is supplied

If the user pastes text, return the corrected text in the same shape they gave it, and the change summary separately.

## Verification before delivery

1. The file opens and validates against its schema where a validator is available.
2. Structural counts match the original: parts, paragraphs, tables, charts, images, sections.
3. `scripts/diff_text.py original revised` returns only the intended changes, and every removal has been put through scan item 39.
4. No character was introduced that the source did not use: em dashes, en dashes, curly quotes, non-breaking hyphens, emoji, ornamental symbols. Characters already present in reproduced titles, names, quoted wording and references are left exactly as they are; the rule bars introduction, not presence.
5. Hidden characters already in the file are inspected, not only those the edit introduced: `scripts/diff_text.py` reports every hidden Unicode character present in the revised file with its class, count and location, marked pre-existing or introduced. An introduced invisible control is removed. A pre-existing one is removed only where it does not belong to source-controlled text, protected wording, a formula, a field code or an identifier, and is otherwise left and recorded. Arabic and other language-dependent joiners and directional marks are preserved. Nothing is removed or normalized automatically.
6. Package and metadata hygiene has been run per `metadata-hygiene.md` on every Office or PDF file being delivered, its log has been read, and its findings are carried into the report.
7. State exactly which checks were performed. Never claim a file was opened, rendered, tested in a named application, repaired or validated unless that was actually done. No native application is available in this runtime, so open-and-recalculate verification is stated as not performed and, for a file intended for formal external issue, recorded as a manual pre-issue item for the user.
