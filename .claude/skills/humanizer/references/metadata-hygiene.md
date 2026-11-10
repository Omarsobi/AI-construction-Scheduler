# Package and metadata hygiene

Run this on every Office or PDF file this skill delivers, not only on a document described as externally issued. Tool, add-in and local-path metadata that survives into an internal working copy travels with that copy when it later becomes an issued document.

This is delivery verification, not a writing review and not general document QA. It operates on the file package. It never changes wording, figures, formulas, cell values, slide content or visible document text.

Character cleanup and metadata hygiene are separate operations and stay separate. Do not fold either into the other.

## Purpose and limits

The purpose is document hygiene, privacy, removal of unnecessary add-in and tool integration metadata, removal of local working paths, and professional issue control.

It must not falsify authorship, alter approved revision history, remove legitimate approvals or signatures, fabricate another creator or author, state that AI was not used, make unsupported claims about provenance, or target or claim to defeat AI-detection systems. The limitation in `SKILL.md` stands: this skill does not conceal AI use where an organization, client, law, regulation, contract, policy or professional standard requires disclosure.

## What is removed, what is reported, what is preserved

**Visible content.** A tool name inside something a reader sees is subject matter, not provenance. That covers the document body, worksheets, slides and shared strings, and equally charts, drawings, diagrams and chart sheets, whose titles and labels are business content. A chart titled "OpenAI Adoption" is reported as content for a reviewer's eye and never fails the package result.

**Plain text.** A `.txt` or `.md` file carries no package and no document properties, so there is nothing to sanitize and no hygiene result to give. A tool name in such a file is visible content, and it may well be the subject matter, so it is recorded as an informational note and never as a failure. Nothing in a text file is changed by this procedure. The trace inspection below still applies to a text file: a citation token, the ChatGPT tracking parameter or a hidden character is a generation artifact rather than a tool name, and is classified with its own result line. A byte-order mark at the very start of a text file is a valid encoding signature and is not reported.

**Removed where found, subject to the implementation rules below:**

- Office web-extension parts whose own content carries a tool, add-in or local-path marker, or whose Office Store reference id is a known writing-assistant add-in (see below), with their relationship entries, their task-pane entries and their content-type declarations. An extension carrying no marker is a legitimate add-in: it is preserved and reported, and the task pane keeps its other entries
- custom document properties whose name is a known integration key, currently `claude.fileId` and `GrammarlyDocumentId`, or whose name or value is a local working path. An integration key is matched on the whole name and case-insensitively, never as a substring. The whole property element is removed. A property carrying only a tool name, such as `ProjectName = OpenAI Headquarters`, is legitimate metadata until someone says otherwise: it is reported for a decision and never deleted automatically
- the Excel absolute-path record `x15ac:absPath` in `xl/workbook.xml`, which is where a workbook keeps the local folder it was last saved in and which no visible content or workbook function depends on
- `HyperlinkBase` where its value is a local user path, such as `C:\Users\<user>\Documents\Claude\...` or the macOS equivalent. The test is the path, not a keyword: a legitimate URL that happens to carry a tool name in its host is not a working path and the field is left alone. The whole XML value is cleared; a path is never edited out of the middle of a value. A path or keyword found in an author or company field is reported instead, never cleared without an instruction
- temporary application identifiers and external application references that no document function depends on

**Grammarly and QuillBot metadata (Rev31, custom-property rule corrected at Rev33).** Both tools are writing assistants that can leave integration metadata in a file. Their traces are identified wherever the procedure looks. Confirmed integration residue is removed; anything else naming either tool is reported, because a tool name alone does not show that an item is disposable:

- **Removed automatically in `.docx`, `.pptx` and `.xlsx`.** `GrammarlyDocumentId`, which the Grammarly add-in and desktop application write into `docProps/custom.xml`, removed by name. An Office web extension carrying either name, or whose Office Store reference id is a known writing-assistant add-in, matched on the whole id and case-insensitively: `WA200001011` (Grammarly for Microsoft Word) and `WA200000368` (QuillBot). This matters because Word persists an add-in's task pane by its store id alone, with no tool name anywhere in the part. The extension goes with its task-pane entry, relationships and content-type declarations. No visible content or document function depends on any of these.
- **Detected and reported, never removed automatically.** Any other custom property naming Grammarly or QuillBot in its name or value, such as `ClientName = QuillBot`, `GrammarlySessionRef` or a value reading `QuillBot Paraphraser`: it may name a client, a vendor or a licence, so it is kept and fails the result until a decision is recorded with `--accept 'docProps/custom.xml|NAME|VALUE|REVIEWER|REASON'`, which keeps the field and clears that exact value only. Rev31 removed these properties; that rule is superseded. A Grammarly or QuillBot name in a core or app property (title, subject, keywords, author, company and the like), in a custom XML part, in a relationship target, in PDF metadata, or in visible document content. Removal there could change content, provenance or a document binding, so the finding goes to the operator. A name in a descriptive or provenance field fails the package result until it is resolved under the ordinary field-context rules; a name inside visible text a reader sees is subject matter, is reported only, and does not fail the result.
- **Browser-extension markup in text files.** The Grammarly and QuillBot browser extensions inject markup into web pages, and it survives when that HTML is pasted into a `.md` or `.txt` file: `data-gr-ext-installed`, `data-new-gr-c-s-check-loaded`, `<grammarly-extension>` and `<quillbot-extension-portal>` or another `quillbot-extension` element. The script reports it and changes nothing; the edit removes it as a generation artifact under rule 10.

The store ids were checked against the Office Store listing for each asset on 29-Sep-26. A different writing-assistant add-in is not caught by id until its id is added to `WEBEXT_STORE_IDS` in the script; it is still caught where its part carries a listed tool name.

Classify these findings as writing-assistant integration metadata. They record that the Grammarly or QuillBot add-in, extension or application touched the file, nothing more. They do not establish generative AI use or AI authorship, and are not reported as evidence of either. The log carries that statement as a closing section whenever such a finding appears, so a reader of the log cannot take the finding for something it is not.

**Generator-library metadata (Rev37).** Libraries that build Office and PDF files write their own name into the file's metadata by default: python-docx (`creator`, and `description` "generated by python-docx"), python-pptx (`description` "generated using python-pptx", `lastModifiedBy` "Steve Canny"), openpyxl (`creator`, and `Application` "Microsoft Excel Compatible / Openpyxl"), PptxGenJS (`creator`, `lastModifiedBy`, `title` and `subject`), the docx npm library (`creator` and `lastModifiedBy` "Un-named"), and ReportLab, pdf-lib, pypdf and wkhtmltopdf (PDF `/Producer`, `/Creator`, `/Author` and the XMP equivalents). The names python-docx, python-pptx, openpyxl, PptxGenJS, ReportLab, pdf-lib, pypdf and wkhtmltopdf are matched case-insensitively and handled by the existing field context, with no new deletion:

- in a provenance field (`creator`, `lastModifiedBy`, `Company`, `Manager`, `Application`, `AppVersion`, `Template`, PDF `/Author`, `/Creator`, `/Producer`, XMP `CreatorTool`): a FAIL until resolved. An author field changes only under `--author` or `--blank-author`; `Application` and the other fields are never overwritten and are cleared only by a recorded `--accept` decision; a PDF is not edited and is corrected at source;
- in a descriptive field (`title`, `subject`, `description`, `keywords`, `category`): REVIEW REQUIRED until a decision is recorded with `--accept`, because the name may be the subject of the file;
- in a custom property: reported, kept, REVIEW REQUIRED until `--accept`;
- in visible content: an informational finding, never edited.

The default values `Steve Canny` and `Un-named` in an author field are reported only: they are not replacement targets and not failures. The python-docx template dates (created and modified 2013-12-23T23:15:00Z) and python-pptx template dates (created 2013-01-27T09:14:16Z, modified 2013-01-27T09:15:58Z), with the revision value beside them, are reported only. Every generator finding indicates programmatic file generation. None establishes that AI wrote the content, and the log carries that statement as a closing section whenever such a finding appears.

**Citation tokens and link tracking (Rev37).** Generation-only citation tokens in document text are detected in every text-bearing part, at paragraph level so a token split across runs is still seen: `contentReference[oaicite:N]{index=N}`, `oaicite:N`, ChatGPT handles of the form `turn` + number + source type + number (`turn0search3`, `turn0click1`, `turn0fetch2`, `turn0view1`, `turn0news1` and the other source types), the `cite`, `filecite` and `navlist` forms with their private-use wrappers, and `【n†source】` markers. At ai-language-fix Rev3, `oai_citation:N` and the `{"attribution":{"attributableIndex":"X-Y"}}` fragment are confirmed tokens as well, and `attached_file`, `grok_card`, `[web:N]` and a bare `attributableIndex` are REVIEW REQUIRED residues that are never removed automatically. A confirmed token is a FAIL until it is removed in the edit (`scripts/clean_artifacts.py`). An incomplete or stray residue, a confirmed token standing between quotation marks, which may be the subject of the text, and any token inside a formula or a tracked change are REVIEW REQUIRED, cleared by removing them in the edit or by `--accept 'PART|citation|TOKEN|REVIEWER|REASON'`. The exact parameter `utm_source=chatgpt.com`, or `utm_source=openai` (Rev3), in an external hyperlink target, a field-code link or URL text is a FAIL until removed; inside a formula it is REVIEW REQUIRED. This detection is separate from the rule that an ordinary http or https link is functional content for tool-name matching: a link is still never a tool-name trace, and only that exact parameter is an artifact. Ordinary words, legitimate citation identifiers and unrelated URL parameters are not matched. In a PDF the page text and link annotations are read where a PDF parser is installed; a PDF is never edited, so a confirmed finding there is corrected at source.

**Hidden Unicode (Rev37, variation selector runs added at Rev38).** Every text-bearing part is read for hidden characters, formatting parts (styles, numbering, settings, font table, themes, slide layouts and masters) excepted, since a Symbol-font bullet is a private-use character by design. Three classes:

- invisible controls: U+200B, U+2060 to U+2064, U+FEFF inside text, U+202A to U+202E, U+2066 to U+2069 the tag characters U+E0000 to U+E007F, and any variation selector in a run of two or more consecutive selectors from U+FE00 to U+FE0F or U+E0100 to U+E01EF, counted per selector and reported once under the identifier `VS-RUN` (Rev38). Introduced since the `--baseline`: FAIL. Pre-existing, or no baseline supplied: REVIEW REQUIRED, cleared by removing it in the edit where it is not source-controlled, or by `--accept 'unicode|U+XXXX|present|REVIEWER|REASON'` (for a run, `--accept 'unicode|VS-RUN|present|REVIEWER|REASON'`);
- language-dependent: U+200C, U+200D, U+200E and U+200F, which Arabic and other scripts need for joining and direction. Always informational, always preserved, never a failure;
- informational: U+00AD, U+202F, a single variation selector (U+FE00 to U+FE0F or U+E0100 to U+E01EF) after a base character, such as an emoji presentation selector or an ideographic variant, and the private-use range U+E000 to U+F8FF. U+202F stays informational here because it is legitimate beside a digit, a unit or French punctuation; between ordinary English words it is a moderate trace and is replaced with a normal space in the edit (rule 10). `scripts/clean_text.py` applies the same test to U+00A0 and U+202F: beside a digit the character is kept, elsewhere it is converted (ai-language-fix Rev3).

Nothing is removed or normalized automatically. Hidden characters in PDF text are not classified, because what an extractor returns depends on the fonts.

**Outcomes (Rev37).** Every scan, clean, recertification and certification record ends in one of four outcomes, applied the same way everywhere:

- PASS: every mandatory check passes and nothing is left to disclose;
- PASS WITH INFORMATIONAL FINDINGS: every mandatory check passes, and informational or legitimate traces remain and are listed in the log: a tool name in visible content, a language-dependent or informational hidden character, a library default value or template date, or an accepted finding;
- REVIEW REQUIRED: an ambiguous finding needs a human decision before correction or certification: a tool or generator name in a descriptive field or custom property, a pre-existing invisible control, an ambiguous citation residue, or a finding inside a formula or tracked change;
- FAIL: a confirmed defect remains or a required check fails: residue the clean should have removed, a confirmed citation token or tracking parameter, an introduced invisible control, a tool or generator name in a provenance field, an annotation discrepancy, a structural defect, or an inspection that could not be completed.

Only the first two are passes and only they certify a file. Exit status is 0 for them and 2 for the others. None of these outcomes says anything about statistical text watermarks or model fingerprints, which this procedure cannot detect or remove.

**Annotations, that is cell comments, notes and threaded comments, and document comments.** An annotation that was already in the file is protected source content. It is not deleted, not rewritten, its author is not changed, and its text is not normalized, reformatted, summarized or improved. An annotation created during processing is a trace and is removed.

The skill never creates an annotation of its own. It does not comment to explain an edit, justify a correction, record reasoning, flag a problem, offer a suggestion, describe what it changed or leave an implementation note. Anything of that kind belongs in the log or the chat, never in the deliverable.

Before the first modification to a file, preserve the original input as the immutable annotation baseline. Every annotation check compares the final deliverable against that preserved pre-edit file. A baseline created after editing has started is not a baseline.

Identity and preservation are separate things. The locator says where an annotation sits and is used to find it: part and cell reference for a legacy comment, part and id for a threaded or a Word comment. Identity includes the part, so a comment on Sheet2 is never mistaken for the comment on Sheet1 at the same cell reference.

What is protected is the whole annotation, not its visible text, and not only its own node. The baseline holds a canonical form of the complete annotation XML together with its author or person and the records that support it: for a cell comment its note shape in the VML drawing and the worksheet `legacyDrawing` reference that makes the notes display, for a threaded comment the complete person record it names, for a Word comment its commentsExtended, commentsIds and commentsExtensible records, its anchors in the body, and the relationship that attaches the comments part to the document. A comment whose anchors are gone is attached to nothing and can be ignored when the document loads, so a deleted anchor is reported and the run fails: its position cannot be inferred and it is put back by hand. Where the anchors sit is protected as well as the anchors themselves: the part, the anchor's kind, the index of the paragraph holding it, that paragraph's content and the anchor's exact offset within it. Text contributes characters; functional content such as a break, tab or drawing contributes a token. Moving a comment within one paragraph or across a break is detected even where its id and anchor XML are untouched. Prefix changes and splitting a text run without changing its text do not change this context. A relocated comment is never moved back on a guess: the file is left as it is, the run fails, and the comment is named for manual resolution. The relationship is unambiguous and is restored. An annotation whose locator matches but whose protected state differs anywhere has been altered, whatever the change: rewritten text, a dropped bold run, an edited timestamp, a changed providerId on the person, a flipped done flag on a support record, an edited note shape. The annotation and the support records are restored in full.

Restoration reconciles the whole support set, not only the records that are still there. A baseline record that was altered is replaced with the baseline version. A baseline record that was deleted is put back, and where the whole part had gone, the part, its relationship and its content-type declaration come back with it. For a cell comment that chain runs the whole way: the VML part, its note shape, the worksheet relationship, the content-type declaration and the worksheet `legacyDrawing` reference. The `legacyDrawing` goes back where the baseline had it, not at the end of the worksheet: worksheet children are ordered by the schema and `extLst` legitimately follows `legacyDrawing`, so the element that followed it in the baseline is recorded and the reference is put back in front of that element. Validation confirms that a worksheet which had a `legacyDrawing` in the baseline still has it, that it matches, and that it has not moved. A record added during processing that the baseline did not have is removed, and where its part did not exist in the baseline, the part goes with it.

Canonicalization normalizes serialization only. A namespace prefix is an alias, so the namespace URI is kept and the prefix is not, and attributes are sorted. Content is never normalized: text is compared exactly, so a double space that becomes a single space is a change. One equivalence is deliberate and defined: the `authorId` on a legacy cell comment is an index into the part's author list, not content, so the author is compared by name and reordering the author table is not an alteration.

An author entry introduced during processing and used by nothing is removed from every comment part, not only from parts where something else was removed.

PowerPoint slide comments are inspected and reported but never removed automatically, because slide comment identity is not implemented. Where one is absent from the inventory the run says so and it is removed by hand.

The test is the pre-edit inventory. Before any change, every annotation is inventoried: its part, its worksheet and cell reference, its author or person, its text, and the relationship and XML parts that support it. Pass the file as it stood before the work with `--baseline FILE`. Then:

- an annotation matching the inventory exactly is pre-existing and is preserved unchanged;
- an annotation absent from the inventory was created during processing and is removed;
- an annotation matching an inventory entry by position but differing in author or text was altered during processing and is restored exactly, including its author, rather than deleted.

Removal takes only what the new annotation brought with it: its comment entry, its own relationship, its note shape in the VML drawing matched on row and column, and, where the drawing itself was introduced and is now empty, the worksheet `legacyDrawing` reference, the relationship, the part and the content-type declaration, in that order, since the worksheet reference is found through the relationship. A content-type declaration by extension, as VML uses, is removed only where it was introduced during processing and no surviving part needs it. In Word the `commentsExtended` and `commentsIds` records go by paraId and the `commentsExtensible` records by the durableId resolved from `commentsIds`. Infrastructure a pre-existing annotation still needs is never removed. In Word the anchors go with the comment, that is `commentRangeStart`, `commentRangeEnd` and the `commentReference`, so the file does not need repairing. The run holding the reference is removed only where nothing functional is left in it: a run can carry a break, a tab, a drawing or text alongside the reference, and none of that belongs to the comment. Document text is never touched.

Namespace bindings the markup still names are kept. A prefix listed in `mc:Ignorable`, in `mc:Choice/@Requires` or in a similar attribute is referenced by value rather than by use, so the serializer would otherwise drop its declaration and leave an undeclared prefix behind. Declarations are read from the original bytes by their own encoding, so a UTF-16 part is read correctly, and the part is walked with its namespace scope so the URI recorded is the one that was in scope at the element naming the prefix. A declaration elsewhere in the part is not taken as proof that the prefix is in scope where it is used. ProcessContent values are qualified names, so their prefixes are resolved separately from their local names; an unprefixed value uses the default namespace in scope. A referenced prefix bound to different URIs in different scopes cannot be preserved by this serializer. That case fails before a cleaned package is written, with the part and prefix identified. Other required bindings are preserved, and verification checks their original URIs as well as whether they resolve. Nothing is solved by deleting a compatibility attribute or its alternate content.

A baseline is checked before it is trusted. A package that is not sound, that is one missing its content-type manifest, its root officeDocument relationship or that relationship's target, or whose annotation XML will not parse, is no inventory at all. Nor is one whose annotation chain does not hold together: a relationship pointing at a part that is not in the package, or a content-type declaration naming one. A baseline whose comments part is gone while its relationship and declaration remain looks like a file that never had comments, and it must not be trusted to authorize deleting one. The precise defect is reported and the run returns a failure. Where that happens nothing is removed, pruned or restored, author and person entries included.

The same structural requirements apply to the deliverable: the content-type manifest, the root officeDocument relationship, its target and the main part's content type must all be present before any result can be a pass.

Scan mode applies the annotation rule in full, comparing the whole inventory rather than only what the file still holds. An annotation added since the baseline, one that has been altered, one that has been relocated, one that has been deleted, and the absence of a baseline all fail the scan and are named in the log, so a scan cannot report success on a file a clean run would reject.

Where no reliable pre-edit inventory is available, nothing is guessed at. Every annotation is preserved, nothing is removed on the strength of an author name or a phrase, and the condition is reported. The result is not a pass, whether or not the file happens to contain any annotation, because without the inventory the run can certify neither that none was created nor that none was lost earlier in the workflow. Since both skills require the original input to be preserved before the first modification, the inventory should always be available.

Final validation confirms all of it: no annotation exists that was not in the inventory; every pre-existing annotation is still present and unchanged; and no orphaned comment, threaded-comment, person, relationship or VML object was introduced.

The baseline threaded-comment person list is protected. A person entry introduced during processing is removed only where no surviving threaded comment references it. Any other change to the person list is reported and not guessed at.

**Reported for decision, never removed automatically**, because removal can change document function or the record: external links, defined names, custom XML, data connections, embedded and OLE objects, and any keyword hit inside document content rather than metadata.

**Preserved:** formulas, named ranges, data validation, conditional formatting, tables, charts, pivot structures, macros where the approved deliverable legitimately requires them, necessary external links, and every item of legitimate provenance, that is project authorship, approvals, revision history, signatures, document-control data and approved custom properties.

**Field context.** What a tool name means depends on the field it sits in. A provenance field says who or what produced the file: `creator`, `lastModifiedBy`, `Company`, `Manager`, `Application`, `AppVersion`, `Template`, and in a PDF `/Author`, `/Creator`, `/Producer` and `CreatorTool`. A tool name there is a provenance question and fails pending a decision. A descriptive field says what the file is about: `title`, `subject`, `description`, `keywords`, `category`, and in a PDF `/Title`, `/Subject`, `/Keywords`. A tool name there may simply be the subject, so it is reported for a decision rather than treated as provenance. Every field in `docProps/core.xml` and `docProps/app.xml` is inspected, not only the author fields. A local working path in any field is definite in every case.

**Reviewed and accepted markers.** A reported item is not a permanent blocker. An operator can record a decision with `--accept 'PART|FIELD|VALUE|REVIEWER|REASON'`, which matches one exact value, in one named field, of one named part, and is written into the log with the reviewer, the reason and a timestamp the script generates, so the decision is auditable. Use `pdf` as the part for a PDF field.

An acceptance resolves ambiguity only. It can never clear a local filesystem or `file:///` path, a known integration key such as `claude.fileId` or `GrammarlyDocumentId`, a web extension or add-in identified as a tool integration, a structural or package defect, a digital signature, or an indeterminate reading. It deletes nothing, never widens beyond that exact value, and is not a global ignore switch. A different value in the same field is still reported. An entry matching no current finding is listed separately as unmatched rather than under the accepted heading.

An explicit `--author` is itself a decision on `creator` and `lastModifiedBy`, so the name it writes is accepted for those two fields and a legitimate name such as Claude Monet no longer fails the run, unless that name is itself a local path, which no decision clears. `Company` and `Manager` are not covered, since `--author` does not authorize them.

**Author fields.** `dc:creator`, `cp:lastModifiedBy`, `Company` and `Manager` are never altered without an instruction, not even where the value looks like tool metadata. A keyword cannot establish that an author field is disposable, since Claude is also a person's name. Such a value is reported and fails the run pending a decision. `--author` sets `creator` and `lastModifiedBy` only, expanding a self-closing element where the field is empty and creating the field in its correct namespace where it is absent altogether, and leaves `Company` and `Manager` exactly as found. Verification confirms both fields hold the requested value before a pass, because a company and a manager are provenance rather than an author. `--blank-author` blanks all four, and that is the only route by which `Company` or `Manager` is emptied. `HyperlinkBase` is not an authorship field: a local path there is a working path and is cleared as a whole value. Where project procedure requires an Author field, use the actual approved author or preparer. Where it does not, the field may be left blank. Never substitute a false author. `Creator` and `Producer` values naming the software that actually produced the file may remain; do not invent alternative software provenance.

## Provenance marks this procedure does not handle

Added at ai-language-fix Rev3.

- **Content Credentials (C2PA).** The script does not detect them. Editing or cleaning a file invalidates a credential bound to it, in the same way as a digital signature. Where a file is known to carry Content Credentials, treat it as a signed file: do not clean it, and refer it to the owner.
- **Sensitivity labels.** A Microsoft Purview label is information-protection metadata, not an AI marker. Its `MSIP_Label_*` custom properties are document-control data and are preserved.
- **Statistical text watermarks.** They sit in word choice. Nothing here detects or removes them, and no edit under this skill is made for that purpose.

## Implementation rules

Every metadata part is parsed with an XML parser and every element is matched on its local name. This covers core properties, extended properties, custom properties, relationship parts, the content-type part, the task-pane part and the `absPath` record alike. No metadata element is located or removed by string substitution.

XML parts are parsed from their original bytes, with no text prefilter anywhere ahead of the parser, so a part written in UTF-16 or another XML-supported encoding is read by its own declaration rather than being forced through UTF-8 and rejected. Where a cleaned part has to be compared with its original, the two are compared as trees, on namespace URI and local name, so a difference in serialized prefixes is not read as an unauthorized change. Marker scanning then runs on normalized text produced from the parsed tree.

Correctness rests on namespace URIs and local names. Keeping a file's own textual prefixes on write is cosmetic, is attempted on a best-effort basis only, and can never stop a file being processed: a prefix Python reserves for itself, such as `ns0`, is skipped rather than registered, and a failure there is swallowed. A namespace prefix is an alias chosen by whoever wrote the file, so `dc:creator` and `dublin:creator` are the same element and neither is matched literally.

Writing a value goes through the parser as well, so a name holding an ampersand or an angle bracket is escaped rather than corrupting the part. Verification confirms that every XML part in the cleaned package still parses.

One classification routine serves both the inspection run and the post-clean verification. Their coverage cannot drift apart, and a part that is reported rather than cleaned is still examined for markers rather than skipped once it has been identified.

Do not delete package components on a keyword match alone. Before removing any component, check the part itself, its relationships, references to it from parent parts, its content-type declaration, and whether another document or workbook function depends on it.

When removing a web extension or task pane, remove the complete relationship chain and the package declarations, so no orphaned or invalid package is left behind. Preserve unrelated add-ins and extensions unless the hygiene criteria specifically reach them.

Do not remove comments, custom XML, external links, defined names or any other component merely because it exists. Remove them only where the criteria establish that they are unnecessary and removal alters no legitimate content or function.

If removing a component would damage document function, do not remove it. Report it.

Match a relationship on its resolved full target, not on the file name at the end of it. Two relationships can end in the same file name and point at different parts.

Identify XML elements by their local name, not by a namespace prefix, everywhere and not only in the part that first showed the problem. A prefix is an alias chosen by whoever wrote the file: a task pane may be written `wetp:taskpane` or `tp:taskpane`, and a relationship part may be written `<Relationship/>` or `<pr:Relationship/>`. All of those are valid. Parse relationship parts and the content-type part as XML, and use the same parsing when removing an entry and when verifying that retained targets resolve. Literal element matching silently misses the prefixed form, which leaves a dangling relationship to a part that is no longer there, or strands a legitimate add-in, while the run still reports a pass.

A path test must fire on the value, not on a substring inside it. `https://example.com/Users/x` is a URL, not a macOS path, and deleting a property because of it destroys legitimate metadata.

An ordinary `http` or `https` link is functional content, not evidence of authorship, even where the host carries a tool name. A hyperlink to a tool's website is excluded from the residue test, in a relationship target and in a property value alike.

The exclusion is context-specific and does not reach an Office web-extension definition. A service URL pointing at a tool is not a hyperlink in a document, it is the application integration this procedure exists to find, so an extension is classified on its full text with no URL removed.

The URL exclusion runs before local-path detection in any field that may legitimately hold a link, so a path-like segment inside a URL, such as `https://example.com/C:/docs`, is not read as a local working path. A `file:///` URL is a local path and is not excluded. What is not excluded is a local working path, an integration key, or a tool name sitting in a metadata field that has no reason to carry one.

**Signed packages.** A package carrying a digital signature is not cleaned. Rebuilding the zip invalidates the signature, so the script reports the signature parts and stops. Remove the signature, clean, then re-sign; or clean the unsigned source and re-issue.

## Verification, two levels

**Level 1, package verification. Mandatory, and performed by this skill.**

- the package opens as a zip and every member decompresses
- required parts and relationships are present, and every internal relationship target resolves
- structural counts match the original except where a removal accounts for the difference
- content-type overrides all point at a part that is present
- formulas are present and unchanged in number where the task authorized no formula change
- defined names, data validation, conditional formatting, charts, tables and pivot structures are unchanged in count
- literal error residues (`#REF!`, `#VALUE!`, `#NAME?` and similar) are scanned for where technically detectable
- embedded and OLE object parts are unchanged in count
- every retained part outside the authorized set, that is the content-type part, the relationship parts, `docProps`, the task-pane part, a workbook part whose only change is the removal of `absPath`, and any part a comment removal reached, is byte-identical to the original. This is the primary guarantee, and it is stronger than counting anything inside a part
- worksheet formula expressions are compared as text and in order, not merely counted, since a count is unchanged when a formula is rewritten
- every relationship part parses as XML, and every retained web extension is still reachable through its full relationship chain: its part present, its task-pane relationship intact, and the task-pane part still referenced by a parent
- a post-cleaning package scan is run for tool keywords and local paths

The inspection run before cleaning covers the same parts as the verification run after it, relationship parts included. A scan that reports nothing while the later verification finds residue means the two runs disagree, and the earlier reading cannot be relied on.

**A hygiene result is a pass only where that final scan finds nothing at package or metadata level that is a defect or awaits a decision.** Residue that survives the clean is a FAIL, whatever the structural checks say, and a file that fails or awaits review is not issued. A tool-name keyword or path inside document content, that is inside visible text a reader sees, is an informational finding and does not by itself fail the package result, because removing it would be a content edit and this procedure never edits content. A confirmed citation token, the ChatGPT tracking parameter or an introduced invisible control in the content is different: it is a generation artifact, removed in the edit step, and the hygiene result is not a pass while it remains. The outcomes are defined above.

What was actually checked is stated in every case.

**Level 2, native application verification.** Claim this only where Excel, Word or PowerPoint was actually available and actually used. It is not available in this runtime. Where it was not performed, state expressly:

> Excel application open/recalculation verification was not performed.

Adjust the application name to the format. For a file intended for formal external issue, record opening the file in its native application and confirming recalculation and the absence of repair warnings as a manual pre-issue verification item carried by the user. Never present it as completed.

## Format scope

**.docx and .pptx.** Package and metadata hygiene where technically safe.

**.xlsx.** Full package and metadata hygiene. Inspect for: Claude, Anthropic, ChatGPT, OpenAI, Copilot, GPT, Grammarly, QuillBot, `claude.fileId`, `GrammarlyDocumentId`, the writing-assistant add-in store ids `WA200001011` and `WA200000368`, AI-generated, Office web extensions, task panes, add-in relationships, local user paths, unnecessary custom properties, unnecessary custom XML, comments and threaded comments where removal is authorized, unused external links, and unnecessary embedded application identifiers. Named parts to inspect: `xl/webextensions/`, `xl/webextensions/_rels/`, `xl/persons/`, `xl/threadedComments/`, `xl/comments*`, `xl/externalLinks/`, `customXml/`, `docProps/custom.xml`, `docProps/core.xml`, `docProps/app.xml`, workbook relationships, defined names carrying local paths, and connection strings carrying personal or local information.

**.pdf.** The existing rule stands: PDF visible text is not edited in place. Metadata hygiene is a separate matter from text editing. Inspection reads the document information dictionary and any XMP packet, both stored as plain text. It does not search compressed content or object streams: random compressed bytes spell keywords and path fragments by chance, and reporting those as traces is noise rather than detection. Where the metadata sits inside a compressed object stream this routine cannot see it and says so, rather than implying a clean result. Reliable and complete PDF metadata inspection needs a PDF parser, which the package does not carry. Sanitize unnecessary personal, tool, local-path or application-extension metadata only where that can be done without changing visible content or legitimate document-control information.

Where the inspection finds a confirmed tool keyword or local path in the information dictionary or the XMP packet, the result is a failure and the file is not cleared for delivery, because the script performs no PDF sanitation and the trace therefore survives. Sanitize it with a PDF tool or resolve it by hand, and record what was done.

PDF inspection uses a PDF parser where one is installed, `pypdf` or `PyPDF2`, and only that reading is complete enough to support a pass. The XMP packet is read from the XMP stream itself as bytes and parsed from those bytes, so a UTF-16 packet is read by its own declaration rather than mangled by a UTF-8 decode, with the parser's own accessor names as a fallback since those have changed between versions. XMP stores a property either as element text or as an XML attribute, and both forms are valid, so both are read: an attribute is named by its local name and classified exactly as the equivalent element would be. An XMP packet that will not parse is indeterminate. Where the parser reports an XMP packet whose content cannot be read, the result is indeterminate rather than a report that no XMP is present. Without a parser, only plain text can be read, and plain-text reading can never establish that nothing was missed: a hexadecimal string such as `/Author <436c61756465>`, a compressed object stream, or an encoded name all hide metadata from it. The result is then INDETERMINATE and never a pass, whatever was or was not found. Hexadecimal information-dictionary strings are still decoded and reported in that mode, so an obvious trace is at least seen.

The dependency is optional and is not required for any Office format. Install it where PDF clearance matters, or accept that every PDF needs a separate check before issue. Check that the visible approval information, document number, revision, issue date, preparer, reviewer, approver, signatures and stamps are exactly as approved. Where safe sanitation is not technically available, do not claim it was performed; report the remaining manual action.

## Delivery certification

Detection is not the hard part. The failure this section exists to prevent is delivering a file other than the one that passed verification, or calling a run clean when the exact final artefact was never verified.

**Hygiene is the last mutating step.** All content editing, language correction, formatting, formula work and metadata changes happen first. The order is: original file, preserve the baseline, make every edit, run the hygiene clean, take the cleaned candidate, scan that exact candidate, check structural and content integrity, take its fingerprint, deliver that file. Nothing modifies or resaves it afterwards. If anything does, the certificate is void and the clean and the final scan are run again.

**What a file is comes from its bytes, not its name.** For every decision about which controls apply, the package type is read from the content: a zip container, a `[Content_Types].xml`, and the `xl/`, `word/` or `ppt/` structure that says which Office type it is. This governs the scan and the clean as well as recertification: the branch that runs is chosen by the detected type, so a workbook renamed `candidate.md` is scanned and cleaned as a workbook, not read as plain text. It still requires the certificate, the mandatory baseline, the annotation protection and every other Office check. A text file named `.xlsx` is not a workbook and is never certified as one. The extension stays what it always was, a description; it is not the security identity, and a misleading one cannot lower what is required.

The certificate binding is unaffected by a rename, because identity there is the recorded hash. A certified candidate can be renamed without changing its bytes and still recertifies, and the rename removes none of the Office requirements.

A file that begins like a zip package but will not open as one is refused rather than inspected, and a file whose content is not a supported type is refused rather than guessed at.

**Cleaning keeps the package type.** A supported Office source produces a candidate with the same Office extension: `.xlsx` from `.xlsx`, `.docx` from `.docx`, `.pptx` from `.pptx`. Any other destination extension is refused before anything is written, with the source type and the requested extension both named, and the output is never silently renamed to fit.

**The source and the baseline are immutable protected inputs.** The cleaned candidate has to be a separate filesystem object. Before the destination is opened, its identity is resolved and compared with both protected files, and an output that resolves to either is refused with nothing written. Nothing is ever restored after an accidental overwrite, so the refusal comes before mutation, not after.

Identity is checked two ways. Where the destination already exists, the filesystem's own comparison is used, which catches a hard link as well as a symlink or a second path to the same file. Where it does not yet exist, the resolved absolute paths are compared, which catches a relative path, a `..` walk and a symlinked directory. Case is normalized where the platform is case insensitive. Where identity cannot be established the operation is refused rather than risked. Symlink and hard-link detection depends on the platform supporting them; where it does not, the resolved-path comparison still applies. A separate candidate whose name merely resembles the source, such as `file_clean.xlsx`, is a different object and is allowed.

**Report-only pre-delivery inspections (Rev34, corrected at Rev35 and Rev36).** Every scan and clean of a .docx, .xlsx or .pptx also runs `scripts/inspect_content.py` and adds a "Pre-delivery review findings (report only)" section to the log, with a one-line count on stdout. It reads the package and changes nothing, and its findings do not change the hygiene PASS or FAIL.

- Embedded images. Every image part is read, including media folders and the document thumbnail, identified by content, with the standard library. Blocks read: JPEG EXIF, XMP, IPTC and comments; PNG eXIf, XMP and text chunks; TIFF EXIF and GPS in the first image directory and XMP in tag 700; WebP EXIF and XMP. Blocks recognized but not read: JPEG extended XMP, TIFF IPTC (tag 33723), TIFF Photoshop resources (tag 34377), further TIFF image directories and bytes after a WebP container. Each image gets one status: review finding, metadata present, no relevant metadata found, format not inspected (GIF, BMP, EMF, WMF, SVG, HEIF and video, for example) or inspection incomplete (nothing found, and a block was malformed, truncated or not read). Completeness is recorded separately: an image with a finding whose metadata was only partly read keeps the finding and is also counted as not fully inspected, in its own line, the count line and the stdout summary. Findings read before a malformed block are kept. A WebP is walked only within its declared container size and the bytes present; an unfinished chunk header, a short payload or a missing padding byte makes it incomplete. Location, identity, unique identifiers and free text are review findings; device, software and timestamps are reported as present and are not a concern by themselves. Capture times are marked as possible project evidence. GPS coordinates are shown rounded to two decimals and serial numbers shortened, so the log does not become a second copy of the sensitive value. XMP GPS values are converted from degrees,minutes[.fraction] or degrees,minutes,seconds with their N, S, E or W direction before rounding; a value in any other form, with the wrong direction letter or out of range, is withheld and only its presence reported. A coordinate is never shown unrounded, including in an error message. Coordinate handling applies only to fields a metadata schema defines as GPS coordinates (the EXIF GPS directory, XMP `exif:GPSLatitude` and `exif:GPSLongitude`). Free-text location fields (city, state, province, country, country code, location, sub-location) are shown as text, cut at 60 characters, and are never read as coordinates, whatever numbers or punctuation they contain; a coordinate typed into such a field is shown as written. Software names are never treated as a sign of AI use.
- Revisions and hidden content. Word: tracked insertions, deletions and moves with their paragraph number and text, tracked formatting changes, revision authors, hidden text, white text (font color FFFFFF with no shading or highlight on the run itself; paragraph, table-cell and page backgrounds are not read, so the owner checks the background; Word only, ai-language-fix Rev3), hidden drawing objects, styles that hide text, hiding set in the document defaults (`w:docDefaults/w:rPrDefault/w:rPr/w:vanish`, on and off values respected), and revision tracking switched on. Default hiding is reported as cannot be conclusively classified, with the number of styles and runs that switch hiding off; which text is actually hidden is not resolved, and the report does not claim that all text is hidden. Excel: hidden and very hidden sheets, hidden rows and columns, shared-workbook revision logs. PowerPoint: hidden slides, hidden shapes, speaker notes. Each finding is classified as working-state information, potentially unintended issued content, or cannot be conclusively classified, with a recommended review action. Comments stay under the annotation rule.

Nothing found by either inspection is removed, accepted, rejected, revealed or rewritten without an explicit instruction. A part or image that cannot be read is reported as incomplete or not inspected, never as clean. Where the owner decides to remove image metadata or resolve revisions, that is done in the native application or as a separately instructed step, and the file is then scanned and certified again.

**Every write is checked, not only the candidate (Rev32).** Each run also writes a report, by default the input's name with `_metahygiene.md`, or the path given with `--log`. Before anything is read or written, the report destination is checked by the same identity test against the source, the baseline, a supplied `--certificate`, the candidate and, on recertification, the file being recertified; the candidate is checked against the report and the certificate as well as the source and the baseline. A collision is refused with exit status 2, the reason goes to stdout and stderr, nothing is written, and no PASS or certificate is issued. The same check runs on the failure path, so a refused candidate cannot write its report over a protected file. Recertification leaves the candidate, the baseline and the certificate byte-identical; where its default report path is the certificate, it is refused and the run is repeated with `--log` naming a separate file.

**Keep the files apart by name, not by guesswork.** Hold each of these separately and never infer one from another at delivery time: `original_file`, `baseline_file`, `working_file`, `cleaned_candidate`, `verified_final_file`. The clean writes `<name>_clean.<ext>` unless `-o` names another path; the original is never overwritten or silently replaced.

**The certificate.** A successful clean ends with a Final deliverable block naming the file, the verification result, the SHA-256 taken from the file on disk after the final scan, the baseline, and whether anything changed it since. The hash is what ties the verdict to one exact artefact. Deliver the file that carries that hash, and state its name, the verification result and the hash in the reply.

**Fail closed.** Do not say PASS, clean, sanitized, traces removed, hygiene completed or ready for delivery unless the exact final file passed. Where the final file cannot be identified and verified, the result is FAIL or INDETERMINATE and the file is not presented as certified. A scan is not a hygiene pass: it writes no deliverable and certifies nothing.

**Delivery lock.** After the candidate passes and its hash is recorded, do not reopen and save it, rewrite its package, regenerate it, run any tool that mutates it, or make another formatting pass. Read-only inspection is fine. Any change to the hash voids the certificate.

**Re-checking before delivery.** `--recertify` re-checks one exact file against the record issued when it was certified:

```bash
python scripts/metadata_hygiene.py out_clean.xlsx --recertify \\
    --certificate out_metahygiene.md --baseline before.xlsx
```

Two fingerprints bind the check. The deliverable must still hash to the Final SHA-256 in the record, and the baseline offered now must hash to the Baseline SHA-256 in the record. Identity is the recorded hash, never a path and never a file name: a renamed copy of the genuine baseline is accepted because its bytes are the same, and a copy of the cleaned candidate is refused because its bytes are not. The certification record is mandatory for a supported Office file and nothing in it is inferred or reconstructed from the files at hand. A record that cannot be read, is malformed, lacks either fingerprint, carries a value that is not a 64-character hash, or does not record a pass, is a failure.

The baseline itself remains mandatory and must still be a usable Office package, and that requirement does not depend on what the file happens to contain: a workbook with no comment, note, VML or tracked item still needs it. A cleaned candidate is never a baseline. Where only the delivered file is to hand, the genuine pre-edit baseline, or a byte-identical copy of it, has to be found; nothing else will recertify it.

The block reports the state it actually found. Where the recorded hash matches the file, `Modified after final verification` reads No. Where it differs, the run fails, the field reads Yes and both hashes are printed. Where no hash was supplied to compare against, it reads Unknown. The value comes from the same comparison that decides the verdict, so the block cannot say No while the run says the file has changed.

```bash
python scripts/metadata_hygiene.py out_clean.xlsx --recertify \
    --expect-sha <hash from the report> --baseline before.xlsx
```

Run it whenever anything might have touched the candidate, and before delivering.

**Every stage propagates.** A failed clean, a failed integrity check, a missing output file, an unexpected output path or a failed final scan all become the result of the run. Nothing continues to a success response after a failed mandatory stage.

## The script

`scripts/metadata_hygiene.py` performs the inspection, the bounded clean and the Level 1 verification, and writes a log. Standard library only.

```bash
python scripts/metadata_hygiene.py file.xlsx                 # scan, writes nothing
python scripts/metadata_hygiene.py file.xlsx --clean         # writes file_clean.xlsx
python scripts/metadata_hygiene.py file.docx --clean --blank-author
python scripts/metadata_hygiene.py file.docx --clean --author "A. Preparer"
python scripts/metadata_hygiene.py file.pdf                  # inspection only
python scripts/clean_artifacts.py file.docx                  # edit step: citation tokens and link tracking, report only
python scripts/clean_artifacts.py file.docx --clean -o work.docx   # edit step: corrected copy
```

`clean_artifacts.py` is an edit-step tool, run before hygiene. It never touches hidden characters, formulas or tracked changes and is never a substitute for the final scan. In a Markdown file, code is found with the CommonMark block structure (specification 0.31.2): fenced and indented code blocks inside block quotes and list items, nested to any depth, indented code directly after a heading, thematic break or closing fence, and inline code spans, including spans that cross a line break. Code is reproduced exactly and a finding inside it is flagged for review, never removed (Rev39, corrected at Rev40 and Rev41). Paragraph text, including lazy continuation lines and paragraphs inside list items, and the content of HTML blocks are not code and are cleaned as prose. A digitally signed .docx, .xlsx or .pptx is reported and `--clean` refuses it before writing, since a rewrite would invalidate the signature (Rev39). The `--log` destination is checked in every mode, before anything is written, against the source and the actual output, named or defaulted, including hard links, symbolic links and other paths to either (Rev39).

Scan is the default and writes nothing. `--clean` acts on the bounded default set only. Author fields change only under `--blank-author` or `--author`. Everything else in the reported set is left for a decision.

Exit status is 0 on PASS or PASS WITH INFORMATIONAL FINDINGS and 2 on REVIEW REQUIRED, FAIL or a refusal, so the result can be read without parsing the log. Scan mode follows the same rule: finding package-level residue returns 2, so a contaminated file is never reported as a success to whatever called the script.

Read the log before accepting the output. The script reports what it inspected, what it removed, what it retained and every check it ran, including the statement that no native application verification was performed. A clean run of the script is evidence of the checks it lists and of nothing beyond them.

## Reporting

For every file on which hygiene was performed, state:

- what was inspected
- what was removed
- what was deliberately retained, and why
- the package and integrity checks actually performed
- whether a native application was actually used
- the outcome: PASS, PASS WITH INFORMATIONAL FINDINGS, REVIEW REQUIRED or FAIL, with the informational findings listed
- any remaining Claude, Anthropic, ChatGPT, OpenAI, Copilot, GPT, Grammarly, QuillBot or local-path reference, and for a Grammarly or QuillBot item, the classification statement that it is writing-assistant integration metadata rather than evidence of AI use
- any generator-library finding, with the statement that it indicates programmatic generation and is not evidence that AI wrote the content
- any citation token, tracking parameter or hidden character found, and what was done with it
- unresolved manual verification items

Do not declare a file clean unless the post-cleaning scan was actually completed.
