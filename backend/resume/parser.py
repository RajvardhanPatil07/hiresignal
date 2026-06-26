"""Resume parsing engine for PDF and DOCX files."""

from __future__ import annotations

import io
import logging
import re
from typing import Any
from urllib.parse import urlparse

import pdfplumber
from docx import Document

from backend.core.config import get_settings
from backend.core.exceptions import FileValidationError, ResumeParsingError
from backend.models.schemas import (
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section detection patterns
# ---------------------------------------------------------------------------

SECTION_PATTERNS: dict[str, list[re.Pattern]] = {
    "contact": [
        re.compile(r"\b(email|phone|mobile|contact|address|linkedin|github)\b", re.I),
    ],
    "experience": [
        re.compile(r"\b(experience|work|employment|career|professional)\b", re.I),
        re.compile(r"\b(work history|employment history)\b", re.I),
    ],
    "education": [
        re.compile(r"\b(education|academic|university|college|degree|b\.?s\.?|m\.?s\.?|ph\.?d\.?)\b", re.I),
    ],
    "skills": [
        re.compile(r"\b(skills|technical skills|technologies|proficiencies|expertise)\b", re.I),
    ],
    "certifications": [
        re.compile(r"\b(certifications?|licenses?|credentials?|accreditations?)\b", re.I),
    ],
    "projects": [
        re.compile(r"\b(projects|portfolio|open source)\b", re.I),
    ],
    "summary": [
        re.compile(r"\b(summary|objective|profile|about me)\b", re.I),
    ],
}

SKILL_KEYWORDS: set[str] = {
    # Languages
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby",
    "php", "swift", "kotlin", "scala", "r", "matlab", "perl", "lua", "dart",
    # Web
    "react", "angular", "vue", "svelte", "next.js", "nuxt", "django", "flask",
    "fastapi", "express", "node.js", "html", "css", "sass", "less", "tailwind",
    "bootstrap", "jquery", "webpack", "vite", "graphql", "rest", "soap",
    # Data / ML
    "tensorflow", "pytorch", "keras", "scikit-learn", "pandas", "numpy", "scipy",
    "matplotlib", "seaborn", "plotly", "jupyter", "spark", "hadoop", "kafka",
    "airflow", "dbt", "sql", "postgresql", "mysql", "mongodb", "redis",
    "elasticsearch", "snowflake", "bigquery", "databricks", "mlflow",
    # DevOps / Cloud
    "docker", "kubernetes", "terraform", "ansible", "jenkins", "gitlab ci",
    "github actions", "aws", "azure", "gcp", "linux", "nginx", "prometheus",
    "grafana", "helm", "argo", "circleci", "travisci",
    # Mobile
    "flutter", "react native", "ios", "android", "xamarin", "ionic",
    # Other
    "git", "agile", "scrum", "jira", "confluence", "figma", "sketch",
    "tableau", "power bi", "looker", "excel", "vba", "shell", "bash",
}

DEGREE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(ph\.?d\.?|doctorate|doctoral)\b", re.I),
    re.compile(r"\b(master'?s?|m\.?s\.?|m\.?a\.?|mba|mscs)\b", re.I),
    re.compile(r"\b(bachelor'?s?|b\.?s\.?|b\.?a\.?|bscs|be)\b", re.I),
    re.compile(r"\b(associate'?s?|a\.?a\.?|a\.?s\.?)\b", re.I),
]

SENIOR_TITLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(senior|sr\.?|lead|principal|staff|architect|manager|director|vp|head of|chief)\b", re.I),
]

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
PHONE_PATTERN = re.compile(r"[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}")
YEAR_PATTERN = re.compile(r"\b(19[8-9]\d|20[0-3]\d)\b")
PROFILE_URL_PATTERN = re.compile(
    r"(?:(?:https?://)?(?:www\.)?"
    r"(?:github\.com|linkedin\.com|twitter\.com|x\.com|huggingface\.co|"
    r"kaggle\.com|leetcode\.com|hackerrank\.com|codechef\.com|codeforces\.com)"
    r"/[^\s<>\]\[()\"']+)",
    re.I,
)
HTTP_URL_PATTERN = re.compile(r"^https?://", re.I)
RESERVED_PROFILE_SEGMENTS: set[str] = {
    "about",
    "business",
    "company",
    "contact",
    "explore",
    "features",
    "jobs",
    "login",
    "marketplace",
    "orgs",
    "pricing",
    "problems",
    "search",
    "signup",
    "topics",
    "users",
}


def _dedupe_strings(values: list[str]) -> list[str]:
    """Return values in first-seen order with case-insensitive duplicates removed."""
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower().rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _extract_uri_values(value: Any) -> list[str]:
    """Extract URL strings from nested PDF/DOCX metadata structures."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return []

    if isinstance(value, str):
        cleaned = value.strip()
        if HTTP_URL_PATTERN.search(cleaned) or PROFILE_URL_PATTERN.search(cleaned):
            return [cleaned]
        return []

    if isinstance(value, dict):
        urls: list[str] = []
        for nested in value.values():
            urls.extend(_extract_uri_values(nested))
        return urls

    if isinstance(value, (list, tuple)):
        urls: list[str] = []
        for nested in value:
            urls.extend(_extract_uri_values(nested))
        return urls

    return []


def _validate_file(filename: str, content: bytes) -> str:
    """Validate uploaded file type and size.

    Args:
        filename: Original filename.
        content: File byte content.

    Returns:
        Lowercase file extension.

    Raises:
        FileValidationError: If file is invalid.
    """
    settings = get_settings()
    ext = filename.lower().split(".")[-1] if "." in filename else ""

    if f".{ext}" not in settings.ALLOWED_RESUME_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file format '.{ext}'. "
            f"Allowed: {', '.join(sorted(settings.ALLOWED_RESUME_EXTENSIONS))}"
        )

    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_UPLOAD_SIZE_MB:
        raise FileValidationError(
            f"File too large ({size_mb:.1f}MB). Max: {settings.MAX_UPLOAD_SIZE_MB}MB"
        )

    return ext


def _extract_pdf_text(content: bytes) -> str:
    """Extract text from PDF bytes.

    Args:
        content: PDF file bytes.

    Returns:
        Extracted text string.

    Raises:
        ResumeParsingError: If extraction fails.
    """
    try:
        text_parts: list[str] = []
        link_targets: list[str] = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                for link in getattr(page, "hyperlinks", []) or []:
                    link_targets.extend(_extract_uri_values(link))
                for annot in getattr(page, "annots", []) or []:
                    link_targets.extend(_extract_uri_values(annot))
        if link_targets:
            text_parts.append("\n".join(_dedupe_strings(link_targets)))
        return "\n".join(text_parts)
    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        raise ResumeParsingError(f"Failed to extract PDF text: {exc}") from exc


def _extract_docx_text(content: bytes) -> str:
    """Extract text from DOCX bytes.

    Args:
        content: DOCX file bytes.

    Returns:
        Extracted text string.

    Raises:
        ResumeParsingError: If extraction fails.
    """
    try:
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        link_targets = [
            rel.target_ref
            for rel in doc.part.rels.values()
            if "hyperlink" in rel.reltype and rel.target_ref
        ]
        return "\n".join([*paragraphs, *_dedupe_strings(link_targets)])
    except Exception as exc:
        logger.error("DOCX extraction failed: %s", exc)
        raise ResumeParsingError(f"Failed to extract DOCX text: {exc}") from exc


def _detect_sections(text: str) -> list[str]:
    """Detect which resume sections are present.

    Args:
        text: Full resume text.

    Returns:
        List of detected section names.
    """
    found: list[str] = []
    for section, patterns in SECTION_PATTERNS.items():
        for pat in patterns:
            if pat.search(text):
                found.append(section)
                break
    return found


def _extract_email(text: str) -> str:
    """Extract email from text."""
    match = EMAIL_PATTERN.search(text)
    return match.group(0) if match else ""


def _extract_phone(text: str) -> str:
    """Extract phone number from text."""
    match = PHONE_PATTERN.search(text)
    return match.group(0) if match else ""


def _normalize_profile_url(url: str) -> str:
    """Normalize a profile URL found in resume text."""
    cleaned = url.strip().rstrip(".,;:)]}>\"'")
    if not re.match(r"^https?://", cleaned, re.I):
        cleaned = f"https://{cleaned}"
    return cleaned


def _is_supported_profile_url(url: str) -> bool:
    """Return true when a URL points to a candidate profile or owned public work."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    parts = [part for part in parsed.path.split("/") if part]

    if host == "github.com":
        return bool(parts) and parts[0].lower() not in RESERVED_PROFILE_SEGMENTS
    if host == "linkedin.com":
        return len(parts) >= 2 and parts[0].lower() in {"in", "pub"}
    if host in {"twitter.com", "x.com"}:
        return bool(parts) and parts[0].lower() not in RESERVED_PROFILE_SEGMENTS
    if host == "huggingface.co":
        if not parts:
            return False
        if parts[0].lower() in {"models", "datasets", "spaces"}:
            return len(parts) >= 2
        return parts[0].lower() not in RESERVED_PROFILE_SEGMENTS
    if host == "kaggle.com":
        return bool(parts) and parts[0].lower() not in {"code", "competitions", "datasets", "models"}
    if host == "leetcode.com":
        return bool(parts) and parts[0].lower() not in {"contest", "discuss", "problems"}
    if host == "hackerrank.com":
        return bool(parts) and parts[0].lower() not in RESERVED_PROFILE_SEGMENTS
    if host == "codechef.com":
        return len(parts) >= 2 if parts and parts[0].lower() == "users" else bool(parts)
    if host == "codeforces.com":
        return len(parts) >= 2 if parts and parts[0].lower() in {"profile", "users"} else bool(parts)
    return False


def _extract_profile_urls(text: str) -> list[str]:
    """Extract public profile URLs from resume text."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in PROFILE_URL_PATTERN.finditer(text):
        url = _normalize_profile_url(match.group(0))
        if not _is_supported_profile_url(url):
            continue
        key = url.lower().rstrip("/")
        if key not in seen:
            seen.add(key)
            urls.append(url)
    return urls[:20]


def _extract_name(text: str) -> str:
    """Extract candidate name from the top of the resume.

    Uses heuristics: first substantial line that looks like a name.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for line in lines[:10]:
        # Skip lines with common non-name patterns
        if any(kw in line.lower() for kw in [
            "resume", "cv", "curriculum", "page", "email", "phone",
            "address", "linkedin", "github", "summary", "objective",
        ]):
            continue
        # Name should be 2-4 words, mostly alphabetic
        words = line.split()
        if 2 <= len(words) <= 4 and all(w.isalpha() or w in "'-" for w in words):
            return line.title()
    return ""


def _extract_skills(text: str) -> list[str]:
    """Extract skills from resume text using keyword matching.

    Also attempts to find a dedicated skills section.
    """
    text_lower = text.lower()
    found: set[str] = set()

    # Direct keyword matching
    for skill in SKILL_KEYWORDS:
        # Use word boundary matching
        pattern = re.compile(r"\b" + re.escape(skill) + r"\b", re.I)
        if pattern.search(text_lower):
            found.add(skill)

    # Try to extract from skills section
    skills_section = _extract_section(text, ["skills", "technical skills", "technologies"])
    if skills_section:
        # Split by common delimiters
        parts = re.split(r"[,;|•\-–—]", skills_section)
        for part in parts:
            part = part.strip().lower()
            if 1 <= len(part) <= 40 and part.isalpha() or " " in part:
                found.add(part)

    return sorted(found)


def _extract_section(text: str, section_headers: list[str]) -> str:
    """Extract text content under a specific section header.

    Args:
        text: Full resume text.
        section_headers: Possible section header names.

    Returns:
        Section content or empty string.
    """
    lines = text.split("\n")
    capturing = False
    content_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Check if this line is a section header
        if any(re.search(rf"\b{re.escape(h)}\b", stripped, re.I) for h in section_headers):
            capturing = True
            continue
        # Stop at next section header (heuristic: short, all caps, or ends with colon)
        if capturing:
            if stripped and len(stripped) < 30:
                if stripped.isupper() or stripped.endswith(":"):
                    # Check if it's another section
                    for other_section, patterns in SECTION_PATTERNS.items():
                        if any(p.search(stripped) for p in patterns):
                            return "\n".join(content_lines)
            if stripped:
                content_lines.append(stripped)

    return "\n".join(content_lines)


def _extract_experience(text: str) -> list[ExperienceEntry]:
    """Extract work experience entries from resume text.

    Uses heuristic parsing to find job entries with dates, titles, and companies.
    """
    entries: list[ExperienceEntry] = []
    exp_section = _extract_section(text, ["experience", "work", "employment", "professional"])

    if not exp_section:
        return entries

    # Split by year patterns or bullet points that start entries
    lines = exp_section.split("\n")
    current_entry: dict[str, Any] = {}

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Look for date ranges
        date_match = re.search(
            r"(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2}|present|current|now)",
            line, re.I,
        )

        if date_match or (any(kw in line.lower() for kw in [
            "engineer", "developer", "manager", "lead", "architect", "analyst",
            "consultant", "director", "specialist", "scientist", "designer",
        ]) and len(line) < 100):
            # Save previous entry if exists
            if current_entry:
                entry = _build_experience_entry(current_entry)
                if entry:
                    entries.append(entry)
            current_entry = {"header": line, "description": ""}
            if date_match:
                current_entry["start_date"] = date_match.group(1)
                end_raw = date_match.group(2)
                current_entry["end_date"] = "Present" if end_raw.lower() in ("present", "current", "now") else end_raw
        elif current_entry:
            current_entry["description"] += " " + line

    # Save last entry
    if current_entry:
        entry = _build_experience_entry(current_entry)
        if entry:
            entries.append(entry)

    return entries[:10]  # Cap at 10 entries


def _build_experience_entry(raw: dict[str, Any]) -> ExperienceEntry | None:
    """Build an ExperienceEntry from raw parsed data."""
    header = raw.get("header", "")
    desc = raw.get("description", "")

    # Extract years
    years = 0.0
    start = raw.get("start_date", "")
    end = raw.get("end_date", "")
    if start and end:
        try:
            start_y = int(start)
            end_y = 2024 if end.lower() == "present" else int(end)
            years = max(0.0, float(end_y - start_y))
        except ValueError:
            pass

    # Determine seniority
    is_senior = any(p.search(header) or p.search(desc) for p in SENIOR_TITLE_PATTERNS)

    # Try to extract company and title
    title = ""
    company = ""
    parts = re.split(r"[,|\-|–—@]", header, maxsplit=1)
    if len(parts) >= 2:
        title = parts[0].strip()
        company = parts[1].strip()
    else:
        title = header[:80]

    if not title and not company:
        return None

    return ExperienceEntry(
        company=company,
        title=title,
        start_date=start,
        end_date=end,
        description=desc.strip(),
        years=years,
        is_senior=is_senior,
    )


def _extract_education(text: str) -> list[EducationEntry]:
    """Extract education entries from resume text."""
    entries: list[EducationEntry] = []
    edu_section = _extract_section(text, ["education", "academic", "university", "college", "degree"])

    if not edu_section:
        return entries

    lines = edu_section.split("\n")
    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        # Detect degree type
        degree = ""
        for pat in DEGREE_PATTERNS:
            match = pat.search(line)
            if match:
                degree = match.group(0)
                break

        # Extract year
        year_match = YEAR_PATTERN.search(line)
        year = year_match.group(0) if year_match else ""

        # Institution heuristic: words before degree or after "from"/"at"
        institution = ""
        words = line.split(",")[0].split()
        if words:
            institution = " ".join(words[:6]).strip()

        # Field of study heuristic
        field = ""
        field_match = re.search(r"\bin\s+([A-Za-z\s]+?)(?:,|\.|$)", line, re.I)
        if field_match:
            field = field_match.group(1).strip()

        if degree or institution:
            entries.append(EducationEntry(
                institution=institution,
                degree=degree,
                field=field,
                year=year,
                is_relevant=False,  # Set during scoring
            ))

    return entries[:5]


def _extract_certifications(text: str) -> list[CertificationEntry]:
    """Extract certification entries from resume text."""
    entries: list[CertificationEntry] = []
    cert_section = _extract_section(text, ["certifications", "licenses", "credentials"])

    if not cert_section:
        # Try to find certifications inline
        cert_patterns = [
            re.compile(r"\b(aws\s+(?:certified|solutions?\s+architect|developer|sysops))", re.I),
            re.compile(r"\b(google\s+(?:cloud|professional))", re.I),
            re.compile(r"\b(azure\s+(?:certified|developer|administrator|solutions?\s+architect))", re.I),
            re.compile(r"\b(certified\s+information\s+systems?\s+security\s+professional|CISSP)", re.I),
            re.compile(r"\b(PMP|CAPM|PgMP)\b", re.I),
            re.compile(r"\b(CISA|CISM|CRISC)\b", re.I),
            re.compile(r"\b(TOGAF)\b", re.I),
            re.compile(r"\b(SCRUM|PSM|CSM)\b", re.I),
            re.compile(r"\b(CCNP|CCNA|CCIE)\b", re.I),
            re.compile(r"\b(RHCSA|RHCE)\b", re.I),
            re.compile(r"\b(CKA|CKAD|CKS)\b", re.I),
        ]
        for pat in cert_patterns:
            for match in pat.finditer(text):
                entries.append(CertificationEntry(
                    name=match.group(0),
                    issuer="",
                    year="",
                    is_relevant=False,
                ))
        return entries

    lines = cert_section.split("\n")
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        name = line[:80]
        year_match = YEAR_PATTERN.search(line)
        year = year_match.group(0) if year_match else ""

        # Try to extract issuer
        issuer = ""
        issuer_match = re.search(r"\b(from|by|via)\s+([A-Za-z\s]+?)(?:,|\.|$)", line, re.I)
        if issuer_match:
            issuer = issuer_match.group(2).strip()

        entries.append(CertificationEntry(
            name=name,
            issuer=issuer,
            year=year,
            is_relevant=False,
        ))

    return entries[:10]


async def parse_resume(filename: str, content: bytes) -> ParsedResume:
    """Parse a resume file into structured data.

    Args:
        filename: Original filename (used to determine format).
        content: Raw file bytes.

    Returns:
        ParsedResume with all extracted fields.

    Raises:
        FileValidationError: If file is invalid.
        ResumeParsingError: If parsing fails.
    """
    ext = _validate_file(filename, content)

    # Extract text based on format
    if ext == "pdf":
        raw_text = _extract_pdf_text(content)
    elif ext == "docx":
        raw_text = _extract_docx_text(content)
    else:
        raise FileValidationError(f"Cannot parse '.{ext}' files")

    if not raw_text or len(raw_text.strip()) < 50:
        raise ResumeParsingError(
            "Resume text extraction yielded insufficient content. "
            "The file may be image-based or corrupted."
        )

    # Parse structured data
    sections_found = _detect_sections(raw_text)

    resume = ParsedResume(
        name=_extract_name(raw_text),
        email=_extract_email(raw_text),
        phone=_extract_phone(raw_text),
        skills=_extract_skills(raw_text),
        experience=_extract_experience(raw_text),
        education=_extract_education(raw_text),
        certifications=_extract_certifications(raw_text),
        raw_text=raw_text,
        profile_urls=_extract_profile_urls(raw_text),
        sections_found=sections_found,
        parse_quality=_determine_parse_quality(sections_found, raw_text),
    )

    logger.info(
        "Parsed resume: name='%s', skills=%d, experience=%d, education=%d, certs=%d",
        resume.name, len(resume.skills), len(resume.experience),
        len(resume.education), len(resume.certifications),
    )

    return resume


def _determine_parse_quality(sections: list[str], text: str) -> str:
    """Determine parsing quality based on sections found."""
    essential = {"experience", "skills", "contact"}
    found_essential = len(essential.intersection(sections))

    if found_essential >= 3 and len(text) > 500:
        return "good"
    elif found_essential >= 2 and len(text) > 200:
        return "fair"
    return "poor"
