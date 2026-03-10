from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ResumeSection:
    name: str
    raw_latex: str
    items: list[str] = field(default_factory=list)


@dataclass
class ParsedResume:
    preamble: str = ""
    header: str = ""
    sections: list[ResumeSection] = field(default_factory=list)
    postamble: str = ""
    full_text: str = ""

    def get_section(self, name: str) -> ResumeSection | None:
        name_lower = name.lower()
        for s in self.sections:
            if name_lower in s.name.lower():
                return s
        return None

    def to_plain_text(self) -> str:
        """Convert to plain text for LLM context."""
        lines = []
        for section in self.sections:
            lines.append(f"## {section.name}")
            if section.items:
                for item in section.items:
                    lines.append(f"  - {item}")
            else:
                # Strip LaTeX commands for readability
                clean = _strip_latex(section.raw_latex)
                if clean.strip():
                    lines.append(clean)
            lines.append("")
        return "\n".join(lines)


def _strip_latex(text: str) -> str:
    """Remove common LaTeX commands, keep text content."""
    # Remove comments
    text = re.sub(r"%.*$", "", text, flags=re.MULTILINE)
    # Remove \command{} but keep content
    text = re.sub(r"\\(?:textbf|textit|emph|underline|href)\{([^}]*)\}", r"\1", text)
    # Remove \command without braces
    text = re.sub(r"\\(?:item|vspace|hfill|smallskip|medskip|bigskip|noindent|newline|\\)\s*", " ", text)
    # Remove remaining \commands with optional args
    text = re.sub(r"\\[a-zA-Z]+(?:\[[^\]]*\])?(?:\{[^}]*\})*", "", text)
    # Remove braces
    text = re.sub(r"[{}]", "", text)
    # Collapse whitespace
    text = re.sub(r"\n\s*\n", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def parse_latex_resume(latex_source: str) -> ParsedResume:
    """Parse a LaTeX resume into structured sections."""
    resume = ParsedResume(full_text=latex_source)

    # Extract preamble (before \begin{document})
    doc_match = re.search(r"(.*?)\\begin\{document\}(.*?)\\end\{document\}", latex_source, re.DOTALL)
    if doc_match:
        resume.preamble = doc_match.group(1).strip()
        body = doc_match.group(2).strip()
        resume.postamble = "\\end{document}"
    else:
        body = latex_source

    # Find section boundaries
    # Match \section{Name}, \section*{Name}, or custom section commands like \resumeSection{Name}
    section_pattern = re.compile(
        r"\\(?:section\*?|resumeSection|resumeSubheading|cvsection)\{([^}]+)\}",
        re.IGNORECASE,
    )

    matches = list(section_pattern.finditer(body))

    if not matches:
        # No sections found — try to split on common patterns
        # Look for lines that are all caps or bold as section headers
        alt_pattern = re.compile(r"\\(?:textbf|large|Large|LARGE)\{([^}]+)\}")
        matches = list(alt_pattern.finditer(body))

    if not matches:
        # Last resort — treat entire body as one section
        resume.sections.append(ResumeSection(
            name="Content",
            raw_latex=body,
            items=_extract_items(body),
        ))
        return resume

    # Extract header (content before first section)
    header_end = matches[0].start()
    resume.header = body[:header_end].strip()

    # Extract each section
    for i, match in enumerate(matches):
        section_name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_content = body[start:end].strip()

        items = _extract_items(section_content)

        resume.sections.append(ResumeSection(
            name=section_name,
            raw_latex=section_content,
            items=items,
        ))

    return resume


def _extract_items(latex: str) -> list[str]:
    """Extract bullet items from LaTeX content."""
    items = []

    # Match \item content
    item_matches = re.findall(r"\\item\s*(.*?)(?=\\item|\\end\{|$)", latex, re.DOTALL)
    for item in item_matches:
        clean = _strip_latex(item).strip()
        if clean and len(clean) > 5:
            items.append(clean)

    # Also try \resumeItem{content} pattern
    resume_items = re.findall(r"\\resumeItem\{((?:[^{}]|\{[^{}]*\})*)\}", latex)
    for item in resume_items:
        clean = _strip_latex(item).strip()
        if clean and len(clean) > 5:
            items.append(clean)

    # Also try \resumeItemListStart ... \resumeItemListEnd blocks
    list_blocks = re.findall(
        r"\\resumeItemListStart(.*?)\\resumeItemListEnd", latex, re.DOTALL
    )
    for block in list_blocks:
        block_items = re.findall(r"\\resumeItem\{((?:[^{}]|\{[^{}]*\})*)\}", block)
        for item in block_items:
            clean = _strip_latex(item).strip()
            if clean and len(clean) > 5 and clean not in items:
                items.append(clean)

    return items
