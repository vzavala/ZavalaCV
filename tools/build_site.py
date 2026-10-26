#!/usr/bin/env python3
"""Generate the CV navigator pages from the LaTeX CV and its .bib file.

Usage:
    python tools/build_site.py [CV_DIR]

CV_DIR defaults to the Box folder holding Zavala_Victor_cv.tex,
MyPublicationsvz.bib and the compiled PDF. Every page listed in _toc.yml is
regenerated, so edit the CV (not the .md files) and rerun this script.
"""
import datetime
import re
import shutil
import sys
import unicodedata
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CV_DIR = (Path.home() / "Library/CloudStorage/Box-Box/ZAVALA_ADMIN/CV"
                  / "Zavala_CV_tex/CURRENT")
TEX_NAME = "Zavala_Victor_cv.tex"
BIB_NAME = "MyPublicationsvz.bib"
PDF_NAME = "Zavala_Victor_cv.pdf"

MY_NAME = "**V.M. Zavala**"
SCHOLAR_PROFILE = "https://scholar.google.com/citations?user=a3mvK3gAAAAJ"
ORCID = "https://orcid.org/0000-0002-5744-7378"


# ---------------------------------------------------------------- LaTeX text

ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308",
           "~": "\u0303", "c": "\u0327", "v": "\u030c", "=": "\u0304"}


def _accent(m):
    return m.group(2) + ACCENTS[m.group(1)]


def tex2md(s):
    """Convert a snippet of the CV's LaTeX into MyST Markdown."""
    s = re.sub(r"%.*", "", s)
    s = re.sub(r"\\(vspace|hspace)\*?\{[^}]*\}", "", s)
    s = re.sub(r"\\(noindent|newpage|centering|Large|large|small)\b", "", s)
    s = s.replace("\\\\", " ")
    s = s.replace("CO$_2$", "CO\u2082").replace("C02", "CO\u2082")
    s = s.replace("\\$", "$").replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    # Accents: \'a, \'{a}, {\'a}, \'{\i}, \c{c}, \~n
    s = re.sub(r"\{\\([`'^\"~=])\s*\{?\\?([A-Za-z])\}?\}", _accent, s)
    s = re.sub(r"\\([`'^\"~=])\s*\{?\\?([A-Za-z])\}?", _accent, s)
    s = re.sub(r"\{?\\([cv])\{\\?([A-Za-z])\}\}?", _accent, s)
    s = s.replace("``", "\u201c").replace("''", "\u201d")
    s = re.sub(r"\u201c([^\u201d\"]*)\"", "\u201c\\1\u201d", s)
    s = re.sub(r"`([^`']*)'", "\u2018\\1\u2019", s)
    s = s.replace("---", "\u2014").replace("--", "\u2013").replace("~", " ")
    s = s.replace("\\myname{}", MY_NAME).replace("\\myname", MY_NAME)
    # Innermost-first so nested groups resolve cleanly.
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\{\\(?:bf|bfseries)\s+([^{}]*)\}", r"**\1**", s)
        s = re.sub(r"\{\\(?:em|it|itshape)\s+([^{}]*)\}", r"*\1*", s)
        s = re.sub(r"\\textbf\{([^{}]*)\}", r"**\1**", s)
        s = re.sub(r"\\(?:emph|textit)\{([^{}]*)\}", r"*\1*", s)
        s = re.sub(r"\\href\{([^{}]*)\}\{([^{}]*)\}", r"[\2](\1)", s)
        s = re.sub(r"\\url\{([^{}]*)\}", r"<\1>", s)
        s = re.sub(r"\{([^{}\\]*)\}", r"\1", s)
    s = re.sub(r"\\[A-Za-z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    s = re.sub(r"\*\*\s+", "**", s, count=0) if False else s
    s = re.sub(r"\s+", " ", s).strip()
    return unicodedata.normalize("NFC", s)


# ------------------------------------------------------------ CV structure

HEADER_RE = re.compile(
    r"\\colorbox\{mygray\}\{\\begin\{minipage\}\{\\textwidth\}\s*"
    r"\{\\bf\s+([^}]*)\}\s*\\end\{minipage\}\}")


def split_sections(tex):
    body = tex.split("\\begin{document}", 1)[1].split("\\end{document}", 1)[0]
    heads = list(HEADER_RE.finditer(body))
    sections = {"_HEADER": body[:heads[0].start()]}
    for h, nxt in zip(heads, heads[1:] + [None]):
        chunk = body[h.end():nxt.start() if nxt else len(body)]
        chunk = re.sub(r"^\s*\\vspace\{[^}]*\}\s*\\\\", "", chunk)
        sections[h.group(1).strip().upper()] = chunk
    return sections


def parse_items(block):
    """Parse (possibly nested) itemize environments into a tree."""
    root, stack = [], []
    for tok in re.split(r"(\\begin\{itemize\}|\\end\{itemize\}|\\item\b)", block):
        if tok == "\\begin{itemize}":
            if not stack:
                stack.append(root)
            else:
                parent = stack[-1]
                stack.append(parent[-1]["children"] if parent else root)
        elif tok == "\\end{itemize}":
            if stack:
                stack.pop()
        elif tok == "\\item":
            if stack:
                stack[-1].append({"text": "", "children": []})
        elif stack and stack[-1]:
            stack[-1][-1]["text"] += tok
    for node in walk(root):
        node["md"] = tex2md(node["text"])
    return root


def walk(nodes):
    for n in nodes:
        yield n
        yield from walk(n["children"])


def md_list(nodes, level=0):
    out = []
    for n in nodes:
        out.append("  " * level + "- " + n["md"])
        out.extend(md_list(n["children"], level + 1))
    return out


def paragraphs(block):
    return [tex2md(p) for p in re.split(r"\n\s*\n", block) if tex2md(p)]


# ------------------------------------------------------------- bibliography

def match_brace(s, i):
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("unbalanced braces near: " + s[i:i + 60])


def parse_bib(text):
    entries, seen = [], set()
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        start = text.index("{", m.start())
        body = text[m.end():match_brace(text, start)]
        fields, i = {}, 0
        while True:
            fm = re.compile(r"\s*,?\s*([A-Za-z]+)\s*=\s*").match(body, i)
            if not fm:
                break
            name, i = fm.group(1).lower(), fm.end()
            if i < len(body) and body[i] == "{":
                j = match_brace(body, i)
                value, i = body[i + 1:j], j + 1
            elif i < len(body) and body[i] == '"':
                j = body.index('"', i + 1)
                value, i = body[i + 1:j], j + 1
            else:
                vm = re.compile(r"[^,\s]+").match(body, i)
                value, i = vm.group(0), vm.end()
            fields[name] = value.strip()
        key = m.group(2)
        if key in seen:
            continue
        seen.add(key)
        fields["_key"], fields["_type"] = key, m.group(1).lower()
        entries.append(fields)
    return entries


def initials(first):
    out = []
    for tok in first.replace(".", ". ").split():
        if "-" in tok:
            out.append("-".join(p[0] + "." for p in tok.split("-") if p))
        elif tok.isupper() and len(tok.rstrip(".")) <= 3 and "." not in tok:
            out.extend(c + "." for c in tok)
        else:
            out.append(tok[0] + ".")
    return "".join(out)


def format_author(a):
    a = a.strip()
    if "\\myname" in a:
        return MY_NAME
    if a.lower() == "others":
        return "et al."
    a = tex2md(a)
    if "," in a:
        last, first = [p.strip() for p in a.split(",", 1)]
    else:
        parts = a.split()
        last, first = parts[-1], " ".join(parts[:-1])
    return (initials(first) + " " + last).strip()


def format_authors(field):
    names = [format_author(a) for a in re.split(r"\s+and\s+", field.strip())]
    if len(names) > 1 and names[-1] == "et al.":
        return ", ".join(names[:-1]) + ", et al."
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def format_entry(e):
    title = tex2md(e.get("title", "")).rstrip(".")
    query = urllib.parse.quote_plus('"%s"' % re.sub(r"[*\u201c\u201d]", "", title))
    link_title = title.replace("[", "\\[").replace("]", "\\]")
    authors = format_authors(e.get("author", "")).rstrip(".")
    parts = ["%s. [%s](https://scholar.google.com/scholar?q=%s)." % (
        authors, link_title, query)]
    venue = tex2md(e.get("journal") or e.get("booktitle") or "")
    if e["_type"] == "book":
        venue = tex2md(e.get("publisher", ""))
    details = ""
    if e.get("volume"):
        details += " " + tex2md(e["volume"])
        if e.get("number"):
            details += "(%s)" % tex2md(e["number"])
    if e.get("pages"):
        details += (":" if details else ", ") + tex2md(e["pages"]).replace("-", "\u2013")
    if venue:
        parts.append("*%s*%s," % (venue, details))
    parts.append("%s." % e.get("year", "n.d."))
    if e.get("doi"):
        parts.append("[\\[doi\\]](https://doi.org/%s)" % e["doi"])
    return " ".join(parts)


def by_year(entries):
    groups = {}
    for e in entries:
        groups.setdefault(e.get("year", "n.d."), []).append(e)
    for year in sorted(groups, reverse=True):
        yield year, sorted(groups[year], key=lambda e: tex2md(e.get("title", "")).lower())


def publication_page(title, intro, entries, label):
    years = list(by_year(entries))
    lines = ["# " + title, "", intro, "",
             "**%d publications.** Jump to a year: " % len(entries)
             + " · ".join("{ref}`%s <%s-%s>`" % (y, label, y) for y, _ in years), ""]
    for year, items in years:
        lines += ["(%s-%s)=" % (label, year),
                  "## %s (%d)" % (year, len(items)), ""]
        lines += ["1. " + format_entry(e) for e in items]
        lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------- pages

def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(c.replace("|", "\\|") for c in r) + " |" for r in rows]
    return out


def background_page(sec):
    edu_rows = []
    for p in paragraphs(sec["EDUCATION"]):
        m = re.match(r"\*\*(.+?)\*\*(.*?)\*\*(.+?)\*\*", p)
        if m:
            year = re.search(r"\d{4}", m.group(2))
            extra = re.sub(r"[,\s]*\d{4}[,\s]*", "", m.group(2)).strip(" ,")
            degree = m.group(1) + (" " + extra if extra else "")
            edu_rows.append([degree, m.group(3), year.group(0) if year else ""])
    app_rows = []
    for p in paragraphs(sec["APPOINTMENTS"]):
        m = re.match(r"\*\*(.+?)\*\*\s*\*\*(.+?)\*\*\.?\s*(.*)", p)
        if m:
            app_rows.append([m.group(3).rstrip(". "), m.group(2).rstrip(". "), m.group(1)])
    lines = ["# Education and Appointments", "", "## Education", ""]
    lines += table(["Degree", "Institution", "Year"], edu_rows)
    lines += ["", "## Appointments", ""]
    lines += table(["Period", "Position", "Organization"], app_rows)
    return "\n".join(lines) + "\n"


def honors_page(sec):
    items = [n["md"].rstrip(".") for n in parse_items(sec["HONORS AND AWARDS"])]
    talk = re.compile(r"Lecture|Plenary|Keynote", re.I)
    lectures = [i for i in items if talk.search(i)]
    awards = [i for i in items if not talk.search(i)]
    lines = ["# Honors and Awards", "",
             "%d awards and fellowships, and %d named lectures and plenary or "
             "keynote invitations." % (len(awards), len(lectures)), "",
             "## Awards and Fellowships", ""]
    lines += ["- " + i for i in awards]
    lines += ["", "## Named Lectures, Plenaries and Keynotes", ""]
    lines += ["- " + i for i in lectures]
    return "\n".join(lines) + "\n"


def funding_items(block):
    out = []
    for n in parse_items(block):
        m = re.match(r"(.+?),\s*\*(.+?)\*,?\s*(.*)", n["md"])
        if m:
            out.append("- **%s**  \n  %s · %s" % (m.group(2), m.group(1), m.group(3)))
        else:
            out.append("- " + n["md"])
    return out


def funding_page(sec):
    cur = funding_items(sec["CURRENT RESEARCH FUNDING"])
    past = funding_items(sec["PAST RESEARCH FUNDING"])
    lines = ["# Research Funding", "",
             "%d current and %d past projects. Each entry lists the role, sponsor, "
             "total award (and allocation), years and place of performance."
             % (len(cur), len(past)), "",
             "## Current Projects", ""] + cur + ["", "## Past Projects", ""] + past
    return "\n".join(lines) + "\n"


def nested_page(title, intro, block, as_table=None):
    lines = ["# " + title, ""]
    if intro:
        lines += [intro, ""]
    for n in parse_items(block):
        if n["children"]:
            heading = re.sub(r"\s*\(Former Institution-Department\)", "", n["md"].strip("* "))
            lines += ["## " + heading, ""]
            rows = [as_table(c["md"]) for c in n["children"]] if as_table else None
            if rows and all(rows):
                lines += table(as_table.header, rows)
            else:
                lines += md_list(n["children"])
            lines.append("")
        else:
            lines.append("- " + n["md"])
    return "\n".join(lines) + "\n"


def mentee_row(md):
    m = re.match(r"(.+?)\s*\((.+?)\),\s*(\d{4}(?:\s*-\s*(?:\d{4}|Present))?)\.?\s*(.*)$", md)
    if not m:
        return None
    note = m.group(4).strip(" .()")
    return [m.group(1), m.group(2), m.group(3).replace(" ", ""), note]


mentee_row.header = ["Name", "Former institution", "Years", "Notes"]


def teaching_page(sec):
    rows = []
    for n in parse_items(sec["TEACHING"]):
        m = re.match(r"\*\*(.+?):?\*\*:?\s*(.*)", n["md"])
        if m:
            terms = m.group(2)
            rows.append([m.group(1).rstrip(":"), terms, str(len(terms.split(",")))])
    lines = ["# Teaching", "", "Courses taught at UW-Madison.", ""]
    lines += table(["Course", "Semesters", "Times taught"], rows)
    return "\n".join(lines) + "\n"


def service_page(sec):
    items = [n["md"].rstrip(". ") for n in parse_items(sec["SCIENTIFIC COMMUNITY ACTIVITIES"])]
    cur = [i for i in items if "Present" in i]
    past = [i for i in items if "Present" not in i]
    lines = ["# Scientific Community Activities", "",
             "Editorial roles, leadership positions, committees and conference "
             "organization.", "", "## Current Roles", ""]
    lines += ["- " + i for i in cur] + ["", "## Past Roles", ""] + ["- " + i for i in past]
    return "\n".join(lines) + "\n"


def talks_page(sec):
    lines = ["# Recent Invited Talks", ""]
    body = []
    total = 0
    for n in parse_items(sec["RECENT INVITED TALKS"]):
        m = re.match(r"\*\*(\d{4})\*\*\s*[-\u2013]\s*(.*)", n["md"])
        if not m:
            continue
        venues = [v.strip(" .") for v in m.group(2).split(",") if v.strip(" .")]
        total += len(venues)
        body += ["## %s (%d)" % (m.group(1), len(venues)), "", "; ".join(venues) + ".", ""]
    lines += ["About %d invited talks, seminars and lectures, by year." % total, ""]
    return "\n".join(lines + body)


def software_page(sec):
    rows = []
    for n in parse_items(sec["SOFTWARE PRODUCTS"]):
        m = re.match(r"(.+?)\s*\((.+?)\)\s*<(.+?)>", n["md"])
        if m:
            desc, name = m.group(1), m.group(2)
            if " " in name and " " not in desc:  # e.g. "Lakeland (K-12 Video Game)"
                desc, name = name, desc
            rows.append(["**%s**" % name, desc, "<%s>" % m.group(3)])
        else:
            m = re.match(r"(.+?)\s*<(.+?)>", n["md"])
            rows.append(["**%s**" % m.group(1), "", "<%s>" % m.group(2)])
    lines = ["# Software Products", "",
             "Open-source software and educational products developed by the group.", ""]
    lines += table(["Name", "Description", "Link"], rows)
    return "\n".join(lines) + "\n"


def intro_page(sec, counts):
    head = [tex2md(l) for l in sec["_HEADER"].split("\\\\") if tex2md(l)]
    name = head[0].replace("*", "").replace("Victor M. Zavala", "Victor M. Zavala")
    title_lines = head[1:4]
    email = re.search(r"<([^>]*@[^>]*)>", " ".join(head))
    site = re.search(r"Website:\s*<([^>]*)>", " ".join(head))
    today = datetime.date.today().strftime("%B %-d, %Y")
    lines = ["# " + name, ""]
    lines += ["**" + title_lines[0] + "**  "] + [l + "  " for l in title_lines[1:]]
    lines += ["", " · ".join(filter(None, [
        "[Email](mailto:%s)" % email.group(1) if email else "",
        "[Lab website](%s)" % site.group(1) if site else "",
        "[Google Scholar](%s)" % SCHOLAR_PROFILE,
        "[ORCID](%s)" % ORCID])), "",
        "This site is a navigator for my curriculum vitae. The full CV is long, so "
        "it is split here into short pages that you can browse from the sidebar "
        "or search (press `/` or use the search box).", "",
        ":::{tip}", "Prefer a single document? {download}`Download the full CV (PDF) "
        "<files/%s>`." % PDF_NAME, ":::", "",
        "## What's inside", ""]
    lines += table(["Section", "What you'll find"], counts)
    lines += ["", "*Generated from the LaTeX CV on %s.*" % today, ""]
    return "\n".join(lines)


# ------------------------------------------------------------------- main

TOC = """# Table of contents (generated by tools/build_site.py)
format: jb-book
root: intro
parts:
  - caption: Overview
    chapters:
      - file: background
      - file: honors
  - caption: Research
    chapters:
      - file: funding
      - file: publications/journal
      - file: publications/conference
      - file: publications/books
      - file: patents-industry
      - file: software
  - caption: Mentoring and Teaching
    chapters:
      - file: mentoring
      - file: teaching
  - caption: Service and Outreach
    chapters:
      - file: service
      - file: talks
"""


def main():
    cv_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CV_DIR
    sec = split_sections((cv_dir / TEX_NAME).read_text(encoding="utf-8"))
    bib = parse_bib((cv_dir / BIB_NAME).read_text(encoding="utf-8"))
    kw = lambda k: [e for e in bib if e.get("keywords", "").strip() == k]
    journal, conference, books = kw("article"), kw("conference"), kw("book")

    pages = {
        "background.md": background_page(sec),
        "honors.md": honors_page(sec),
        "funding.md": funding_page(sec),
        "publications/journal.md": publication_page(
            "Journal Publications", "Peer-reviewed journal articles, newest first. "
            "Each title links to a Google Scholar search for the paper.", journal, "journal"),
        "publications/conference.md": publication_page(
            "Conference Publications", "Peer-reviewed conference papers, newest first. "
            "Each title links to a Google Scholar search for the paper.", conference, "conference"),
        "publications/books.md": publication_page(
            "Books and Book Chapters", "Books and book chapters, newest first.", books, "books"),
        "patents-industry.md": nested_page(
            "Patents, Technology Transfer, and Industry Collaborations", "",
            sec["PATENTS, TECHNOLOGY TRANSFER, AND INDUSTRY COLLABORATIONS"]),
        "mentoring.md": nested_page(
            "Research Mentoring", "Postdoctoral researchers and graduate students "
            "advised, with their former institution.", sec["RESEARCH MENTORING"], mentee_row),
        "teaching.md": teaching_page(sec),
        "service.md": service_page(sec),
        "talks.md": talks_page(sec),
        "software.md": software_page(sec),
    }

    mentoring = parse_items(sec["RESEARCH MENTORING"])
    n_mentees = sum(len(n["children"]) for n in mentoring)
    counts = [
        ["[Education and Appointments](background.md)", "Degrees and positions at UW-Madison, Argonne and in industry"],
        ["[Honors and Awards](honors.md)", "Awards, fellowships and named lectures"],
        ["[Research Funding](funding.md)", "Current and past grants"],
        ["[Journal Publications](publications/journal.md)", "%d articles, grouped by year" % len(journal)],
        ["[Conference Publications](publications/conference.md)", "%d peer-reviewed conference papers" % len(conference)],
        ["[Books and Book Chapters](publications/books.md)", "%d books and chapters" % len(books)],
        ["[Patents and Industry](patents-industry.md)", "Patents and industry collaborators"],
        ["[Software](software.md)", "Open-source tools such as Plasmo.jl, MadNLP.jl and InfiniteOpt.jl"],
        ["[Research Mentoring](mentoring.md)", "%d postdocs and graduate students" % n_mentees],
        ["[Teaching](teaching.md)", "Courses taught at UW-Madison"],
        ["[Community Activities](service.md)", "Editorial boards, leadership and conference organization"],
        ["[Invited Talks](talks.md)", "Seminars and lectures by year"],
    ]
    pages["intro.md"] = intro_page(sec, counts)

    for rel, text in pages.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
    (ROOT / "_toc.yml").write_text(TOC, encoding="utf-8")
    (ROOT / "files").mkdir(exist_ok=True)
    shutil.copy2(cv_dir / PDF_NAME, ROOT / "files" / PDF_NAME)
    print("Wrote %d pages: %d journal, %d conference, %d book entries"
          % (len(pages), len(journal), len(conference), len(books)))


if __name__ == "__main__":
    main()
