"""Parse regulatory documents into a three level hierarchy.

Level 1  Document: tier (FEDERAL, STATE, LOCAL, HARDWARE), jurisdiction, title.
Level 2  Section:  MUTCD section (for example 4F.17), NEMA TS 2 clause, or a
                   policy clause, with part, chapter and page provenance.
Level 3  Paragraph: numbered paragraph tagged with its provision type
                   (Standard, Guidance, Option, Support, Clause, Specification).

Provision types matter legally. In the MUTCD a Standard is a mandatory
statement (shall), Guidance is a recommended practice (should), an Option is
permissive (may) and Support is informational. The retriever and the memo
writer both use these labels.
"""

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

from . import config
from .utils import UPPER_CLASS, get_logger, read_json, write_json

LOG = get_logger("ingest")

PROVISIONS = ("Standard", "Guidance", "Option", "Support")
MUTCD_HEADING = re.compile(r"^Section\s+(\d{1,2}" + UPPER_CLASS + r"\.\d{2})\s+(\S.*)$")
CHAPTER_HEADING = re.compile(r"^CHAPTER\s+(\d{1,2}" + UPPER_CLASS + r")\.\s+(.*)$")
PARA_NUMBER = re.compile(r"^(\d{2})(?:\s+(.*))?$")
PAGE_LABEL = re.compile(r"^Page\s+(\d{1,4})$")
PAGE_LABEL_ANYWHERE = re.compile(
    r"^\s*(?:MUTCD 11th Edition\s+Page\s+(\d{1,4})|Page\s+(\d{1,4})(?:\s+MUTCD 11th Edition)?)\s*$", re.MULTILINE)
PAGE_MARKER = "\u0000PAGE "
FURNITURE = re.compile(r"^(Sect\.\s+\S+|December 2023|MUTCD 11th Edition|Page\s+\d+|MUTCD 11th Edition Page\s+\d+|Page\s+\d+ MUTCD 11th Edition)$")
MD_HEADING = re.compile(r"^##\s+((?:Clause|Section)\s+[\d.]+)\s+(.*)$")
NEMA_TOC = re.compile(r"^(?:(Section\s+\d+|\d+(?:\.\d+)*)\s+)?(.+?)\s*\.{4,}\s*(\d+)$")
NEMA_ID_ONLY = re.compile(r"^(\d+(?:\.\d+)+)$")
LOWER_START_WORDS = {"contains", "includes", "describes", "provides", "and", "or", "of", "for", "in", "through"}


@dataclass
class Paragraph:
    para_no: str
    provision: str
    text: str
    page: str


@dataclass
class Section:
    doc_id: str
    section_id: str
    title: str
    chapter: str = ""
    page: str = ""
    paragraphs: list = field(default_factory=list)

    def body(self):
        return " ".join(p.text for p in self.paragraphs)


@dataclass
class Document:
    doc_id: str
    title: str
    tier: str
    citation: str
    path: str
    state_code: str = ""
    jurisdiction_code: str = ""
    sections: list = field(default_factory=list)


def extract_pdf_text(path):
    """Return page separated text, preferring poppler pdftotext and caching the result."""
    cache = config.TEXT_CACHE_DIR / (path.stem + ".txt")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache.read_text(encoding="utf8")
    text = None
    if shutil.which("pdftotext"):
        try:
            subprocess.run(["pdftotext", str(path), str(cache)], check=True, capture_output=True)
            text = cache.read_text(encoding="utf8", errors="replace")
        except (subprocess.CalledProcessError, OSError) as exc:
            LOG.warning("pdftotext failed for %s (%s); falling back to pypdf", path.name, exc)
    if text is None:
        from pypdf import PdfReader

        LOG.info("Extracting %s with pypdf, this can take a few minutes for large manuals", path.name)
        reader = PdfReader(str(path))
        text = "\f".join((page.extract_text() or "") for page in reader.pages)
        cache.write_text(text, encoding="utf8")
    return text


def _clean(line):
    return " ".join(line.replace("\u00a0", " ").split())


def _looks_like_title(title):
    words = title.split()
    if not words or words[0].lower() in LOWER_START_WORDS or title.endswith("."):
        return False
    long_words = [w for w in words if len(w) > 3 and w[0].isalpha()]
    if not long_words:
        return True
    capitalised = sum(1 for w in long_words if w[0].isupper())
    return capitalised / len(long_words) >= 0.6


def parse_provision_text(lines, doc_id, heading_regex, chapter_regex=None, paginate=True):
    """Shared parser for MUTCD style layouts (used for the MUTCD and policy markdown)."""
    sections = {}
    current = None
    provision = "Support"
    para = None
    chapter = ""
    pdf_page = 1
    printed_page = ""

    def close_paragraph():
        nonlocal para
        if current is not None and para is not None and para.text.strip():
            current.paragraphs.append(para)
        para = None

    for raw in lines:
        if "\f" in raw:
            pdf_page += raw.count("\f")
            raw = raw.replace("\f", "")
        if raw.startswith(PAGE_MARKER):
            printed_page = raw[len(PAGE_MARKER):]
            continue
        line = _clean(raw)
        if not line:
            continue
        page_match = PAGE_LABEL.match(line)
        if page_match:
            printed_page = page_match.group(1)
            continue
        if FURNITURE.match(line):
            continue
        if chapter_regex:
            chapter_match = chapter_regex.match(line)
            if chapter_match:
                chapter = chapter_match.group(1) + " " + chapter_match.group(2).title()
                continue
        heading = heading_regex.match(line)
        if heading and _looks_like_title(heading.group(2)):
            close_paragraph()
            if current is not None:
                _keep(sections, current)
            current = Section(doc_id, heading.group(1), heading.group(2).strip(), chapter,
                              printed_page or str(pdf_page))
            provision = "Support"
            continue
        if current is None:
            continue
        if line.rstrip(":") in PROVISIONS and line.endswith(":"):
            close_paragraph()
            provision = line.rstrip(":")
            continue
        number = PARA_NUMBER.match(line)
        expected = str(len(current.paragraphs) + (1 if para is None else 2)).zfill(2)
        if number and number.group(1) == expected:
            close_paragraph()
            para = Paragraph(number.group(1), provision, number.group(2) or "", printed_page or str(pdf_page))
            continue
        if para is None:
            para = Paragraph(str(len(current.paragraphs) + 1).zfill(2), provision, "", printed_page or str(pdf_page))
        para.text = (para.text + " " + line).strip()
    close_paragraph()
    if current is not None:
        _keep(sections, current)
    if not paginate:
        for section in sections.values():
            section.page = ""
            for para in section.paragraphs:
                para.page = ""
    return list(sections.values())


def _keep(sections, section):
    """Keep the richest occurrence of a section id (table of contents entries are dropped)."""
    existing = sections.get(section.section_id)
    if existing is None or len(section.body()) > len(existing.body()):
        sections[section.section_id] = section


def paged_lines(text):
    """Split page separated text into lines, announcing each page's printed label first.

    pdftotext prints the running page label at the top of a page while pypdf
    tends to emit it at the bottom, so the label is located per page before
    parsing and injected as a marker line to keep citations identical.
    """
    lines = []
    for page in text.split("\f"):
        label = PAGE_LABEL_ANYWHERE.search(page)
        if label:
            lines.append(PAGE_MARKER + (label.group(1) or label.group(2)))
        lines.extend(page.splitlines())
    return lines


def parse_mutcd(doc, text):
    lines = paged_lines(text)
    sections = parse_provision_text(lines, doc.doc_id, MUTCD_HEADING, CHAPTER_HEADING)
    return [s for s in sections if s.paragraphs]


def parse_nema(doc, text):
    """Parse the NEMA TS 2 contents, scope and change history into navigable sections."""
    sections = []
    pending_id = ""
    front, scope = [], []
    in_scope = False
    for raw in text.replace("\f", "\n").splitlines():
        line = _clean(raw)
        if not line:
            continue
        if NEMA_ID_ONLY.match(line):
            pending_id = line
            continue
        toc = NEMA_TOC.match(line)
        if toc and not in_scope:
            sid = toc.group(1) or pending_id or toc.group(2).split(" ")[0]
            pending_id = ""
            title = toc.group(2).strip()
            summary = ("NEMA TS 2 2021 contents entry " + sid + " " + title + ", located on page "
                       + toc.group(3) + " of the full standard.")
            sections.append(Section(doc.doc_id, sid, title, "Contents", toc.group(3),
                                    [Paragraph("01", "Specification", summary, toc.group(3))]))
            continue
        if line.startswith("Section 1") and len(line) < 20:
            in_scope = True
            continue
        (scope if in_scope else front).append(line)

    def blockify(lines_, sid, title):
        paragraphs, buffer = [], []
        for ln in lines_:
            buffer.append(ln)
            if ln.endswith(".") and sum(len(b) for b in buffer) > 280:
                paragraphs.append(Paragraph(str(len(paragraphs) + 1).zfill(2), "Specification", " ".join(buffer), ""))
                buffer = []
        if buffer:
            paragraphs.append(Paragraph(str(len(paragraphs) + 1).zfill(2), "Specification", " ".join(buffer), ""))
        return Section(doc.doc_id, sid, title, "Front matter", "", paragraphs)

    if front:
        sections.append(blockify(front, "Front", "Notice, Foreword, History and Revision Summaries"))
    if scope:
        sections.append(blockify(scope, "1", "Scope"))
    return sections


def parse_markdown_policy(doc, text):
    lines = text.splitlines()
    return parse_provision_text(lines, doc.doc_id, MD_HEADING, paginate=False)


def discover_documents():
    """Build the document registry from the manifest plus generated policy files."""
    manifest = read_json(config.KNOWLEDGE_DIR / "manifest.json")
    docs = []
    for entry in manifest["documents"]:
        path = config.KNOWLEDGE_DIR / entry["path"]
        if not path.exists():
            LOG.warning("Knowledge file missing, skipped: %s", path)
            continue
        docs.append(Document(entry["doc_id"], entry["title"], entry["tier"], entry["citation"], str(path),
                             entry.get("state_code", ""), entry.get("jurisdiction_code", ""),
                             [{"parser": entry["parser"]}]))
    from .jurisdictions import LOCALS, STATES

    for state in STATES.values():
        path = config.KNOWLEDGE_DIR / "state" / (state.state_code.lower() + "_dot_signal_policy.md")
        if path.exists():
            docs.append(Document("STATE_" + state.state_code, state.manual_title, "STATE", state.manual_title,
                                 str(path), state.state_code, "", [{"parser": "markdown"}]))
    for local in LOCALS.values():
        path = config.KNOWLEDGE_DIR / "local" / (local.jurisdiction_code.lower() + "_municipal_code.md")
        if path.exists():
            docs.append(Document("LOCAL_" + local.jurisdiction_code, local.ordinance_title, "LOCAL",
                                 local.ordinance_title, str(path), local.state_code, local.jurisdiction_code,
                                 [{"parser": "markdown"}]))
    return docs


def build_index():
    """Parse every document and persist the hierarchical index as JSON."""
    from pathlib import Path

    parsers = {"mutcd": parse_mutcd, "nema": parse_nema, "markdown": parse_markdown_policy}
    out = []
    for doc in discover_documents():
        parser = parsers[doc.sections[0]["parser"]]
        path = Path(doc.path)
        text = extract_pdf_text(path) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf8")
        doc.sections = parser(doc, text)
        LOG.info("Indexed %s: %d sections, %d paragraphs", doc.doc_id, len(doc.sections),
                 sum(len(s.paragraphs) for s in doc.sections))
        out.append(asdict(doc))
    write_json(config.INDEX_PATH, {"documents": out})
    return out


def load_index():
    if not config.INDEX_PATH.exists():
        return build_index()
    return read_json(config.INDEX_PATH)["documents"]
