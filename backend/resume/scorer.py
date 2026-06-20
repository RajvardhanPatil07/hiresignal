"""Resume scoring engine with skill matching, experience analysis, and semantic similarity."""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Optional

import httpx
import numpy as np

from backend.core.config import get_settings
from backend.core.llm_provider import api_base_url, api_headers, api_key
from backend.core.exceptions import LLMError, ScoringError
from backend.models.schemas import (
    CandidateTier,
    CertificationEntry,
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    ResumeScoreBreakdown,
    ResumeScoreResponse,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEGREE_HIERARCHY: dict[str, int] = {
    "phd": 4, "doctorate": 4, "doctoral": 4,
    "master": 3, "mba": 3, "ms": 3, "ma": 3, "mscs": 3,
    "bachelor": 2, "bs": 2, "ba": 2, "bscs": 2, "be": 2,
    "associate": 1, "aa": 1, "as": 1,
}

CERT_RELEVANCE_KEYWORDS: list[str] = [
    "aws", "azure", "google cloud", "certified", "kubernetes", "docker",
    "security", "pmp", "cissp", "scrum", "agile", "machine learning",
    "data science", "python", "react", "angular", "devops", "terraform",
]


def _normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    return " ".join(text.lower().split())


def _extract_job_skills(job_description: str) -> list[str]:
    """Extract required skills from job description.

    Uses keyword matching combined with common tech skill detection.
    """
    from backend.resume.parser import SKILL_KEYWORDS

    jd_lower = _normalize_text(job_description)
    found: set[str] = set()

    # Direct keyword matching against known skills
    for skill in SKILL_KEYWORDS:
        pattern = skill.replace("+", r"\+").replace(".", r"\.")
        if skill in jd_lower:
            found.add(skill)

    # Also look for patterns like "X years of Y experience"
    exp_pattern = r"(?:experience\s+(?:with|in)\s+|proficiency\s+(?:with|in)\s+|knowledge\s+of\s+)([A-Za-z0-9+#.\s]+?)(?:[,;]|\s+(?:required|preferred|plus|and|or)|$)"
    import re
    for match in re.finditer(exp_pattern, jd_lower, re.I):
        skill_guess = match.group(1).strip()
        if 1 <= len(skill_guess) <= 30:
            found.add(skill_guess)

    return sorted(found)


def _compute_keyword_match(
    resume_skills: list[str],
    job_skills: list[str],
) -> float:
    """Compute exact keyword match score (0-25).

    Args:
        resume_skills: Skills extracted from resume.
        job_skills: Skills required by job description.

    Returns:
        Score from 0 to 25.
    """
    if not job_skills:
        return 25.0  # No requirements = full score

    resume_set = set(_normalize_text(s) for s in resume_skills)
    job_set = set(_normalize_text(s) for s in job_skills)

    if not job_set:
        return 25.0

    matches = resume_set.intersection(job_set)
    ratio = len(matches) / len(job_set)

    # Partial credit with diminishing returns
    score = min(25.0, ratio * 25.0)
    return round(score, 2)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    vec_a = np.array(a, dtype=np.float64)
    vec_b = np.array(b, dtype=np.float64)

    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


async def _get_embedding(text: str) -> list[float]:
    """Get an embedding from the configured OpenAI-compatible provider.

    Args:
        text: Text to embed.

    Returns:
        Embedding vector.

    Raises:
        LLMError: If the API call fails.
    """
    settings = get_settings()
    if not api_key(settings):
        raise LLMError("AI provider API key not configured")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{api_base_url(settings)}/embeddings",
                headers=api_headers(settings),
                json={
                    "input": text[:8000],  # Truncate to token limit
                    "model": settings.EMBEDDING_MODEL,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]
    except Exception as exc:
        logger.error("Embedding API failed: %s", exc)
        raise LLMError(f"Failed to get embedding: {exc}") from exc


async def _compute_semantic_similarity(
    resume: ParsedResume,
    job_description: str,
) -> float:
    """Compute semantic similarity between resume and job description (0-15).

    Uses provider embeddings to compute cosine similarity.

    Args:
        resume: Parsed resume data.
        job_description: Job description text.

    Returns:
        Score from 0 to 15.
    """
    # Build resume summary text
    resume_text = f"""
    Skills: {', '.join(resume.skills)}
    Experience: {'; '.join(f"{e.title} at {e.company} ({e.years} years)" for e in resume.experience)}
    Education: {'; '.join(f"{e.degree} in {e.field} from {e.institution}" for e in resume.education)}
    Certifications: {'; '.join(c.name for c in resume.certifications)}
    """

    try:
        resume_embedding = await _get_embedding(resume_text)
        jd_embedding = await _get_embedding(job_description)

        similarity = _cosine_similarity(resume_embedding, jd_embedding)
        # Cosine similarity is [-1, 1], map to [0, 15]
        score = max(0.0, min(15.0, ((similarity + 1) / 2) * 15.0))
        return round(score, 2)
    except LLMError:
        # Fallback: compute a basic text overlap score
        logger.warning("Embedding failed, using fallback text similarity")
        resume_words = set(_normalize_text(resume.raw_text).split())
        jd_words = set(_normalize_text(job_description).split())
        if not jd_words:
            return 0.0
        overlap = len(resume_words.intersection(jd_words)) / len(jd_words)
        return round(min(15.0, overlap * 15.0), 2)


def _score_experience(
    experience: list[ExperienceEntry],
    job_description: str,
) -> float:
    """Score experience depth (0-30).

    Breakdown:
        - Years relevant (15): Total years of experience
        - Seniority (10): Presence of senior/lead roles
        - Industry (5): Keyword overlap with job description
    """
    jd_lower = _normalize_text(job_description)

    # Years (0-15)
    total_years = sum(e.years for e in experience)
    years_score = min(15.0, total_years * 3.0)  # 5 years = 15 pts

    # Seniority (0-10)
    senior_roles = sum(1 for e in experience if e.is_senior)
    seniority_score = min(10.0, senior_roles * 3.0)

    # Industry relevance (0-5)
    industry_score = 0.0
    if experience:
        desc_text = " ".join(e.description for e in experience)
        desc_words = set(desc_text.lower().split())
        jd_words = set(jd_lower.split())
        common = desc_words.intersection(jd_words)
        if jd_words:
            industry_score = min(5.0, (len(common) / len(jd_words)) * 5.0)

    total = years_score + seniority_score + industry_score
    return round(min(30.0, total), 2)


def _score_education_certs(
    education: list[EducationEntry],
    certifications: list[CertificationEntry],
    job_description: str,
) -> float:
    """Score education and certifications (0-20).

    Breakdown:
        - Degree relevance (10): Highest degree level
        - Certifications (10): Relevant certifications
    """
    # Degree score (0-10)
    degree_score = 0.0
    if education:
        max_level = 0
        for edu in education:
            edu_degree = _normalize_text(edu.degree)
            for key, level in DEGREE_HIERARCHY.items():
                if key in edu_degree:
                    max_level = max(max_level, level)
                    break

        if max_level >= 4:      # PhD
            degree_score = 10.0
        elif max_level >= 3:    # Masters
            degree_score = 8.0
        elif max_level >= 2:    # Bachelor
            degree_score = 6.0
        elif max_level >= 1:    # Associate
            degree_score = 3.0
        else:
            degree_score = 2.0  # Some education mentioned
    else:
        degree_score = 0.0

    # Certifications score (0-10)
    cert_score = 0.0
    if certifications:
        relevant_certs = 0
        for cert in certifications:
            cert_name = _normalize_text(cert.name)
            if any(kw in cert_name for kw in CERT_RELEVANCE_KEYWORDS):
                relevant_certs += 1

        # Score based on number of relevant certs (diminishing returns)
        cert_score = min(10.0, relevant_certs * 3.0 + 1.0)
    else:
        cert_score = 0.0

    return round(min(20.0, degree_score + cert_score), 2)


def _score_format_completeness(resume: ParsedResume) -> float:
    """Score format and completeness (0-10).

    Breakdown:
        - ATS-parseable (5): Structured data quality
        - Sections complete (5): Presence of key sections
    """
    # ATS-parseable (0-5)
    ats_score = 0.0
    if resume.parse_quality == "good":
        ats_score = 5.0
    elif resume.parse_quality == "fair":
        ats_score = 3.0
    else:
        ats_score = 1.0

    # Sections complete (0-5)
    essential_sections = {"experience", "skills", "education", "contact"}
    found_sections = set(resume.sections_found)
    section_ratio = len(found_sections.intersection(essential_sections)) / len(essential_sections)
    section_score = min(5.0, section_ratio * 5.0)

    return round(min(10.0, ats_score + section_score), 2)


def _assign_tier(total_score: float) -> CandidateTier:
    """Assign candidate tier based on total score.

    Args:
        total_score: Score from 0 to 100.

    Returns:
        CandidateTier enum value.
    """
    if total_score >= 90:
        return CandidateTier.TIER_1
    elif total_score >= 75:
        return CandidateTier.TIER_2
    elif total_score >= 60:
        return CandidateTier.TIER_3
    return CandidateTier.REJECT


async def score_resume(
    resume: ParsedResume,
    job_description: str,
) -> ResumeScoreResponse:
    """Score a parsed resume against a job description.

    Args:
        resume: Parsed resume data.
        job_description: Full job description text.

    Returns:
        ResumeScoreResponse with total score, breakdown, and tier.

    Raises:
        ScoringError: If scoring computation fails.
    """
    start_time = time.time()
    warnings: list[str] = []

    try:
        # Extract job skills
        job_skills = _extract_job_skills(job_description)

        # SKILL MATCH (0-40)
        keyword_score = _compute_keyword_match(resume.skills, job_skills)
        try:
            semantic_score = await _compute_semantic_similarity(resume, job_description)
        except Exception as exc:
            logger.warning("Semantic similarity failed: %s", exc)
            semantic_score = 0.0
            warnings.append(f"Semantic similarity unavailable: {exc}")

        skill_match = min(40.0, keyword_score + semantic_score)

        # EXPERIENCE DEPTH (0-30)
        experience_depth = _score_experience(resume.experience, job_description)

        # EDUCATION & CERTS (0-20)
        education_certs = _score_education_certs(
            resume.education, resume.certifications, job_description
        )

        # FORMAT & COMPLETENESS (0-10)
        format_completeness = _score_format_completeness(resume)

        # Total
        total = round(skill_match + experience_depth + education_certs + format_completeness, 2)
        total = min(100.0, max(0.0, total))

        elapsed_ms = int((time.time() - start_time) * 1000)

        breakdown = ResumeScoreBreakdown(
            skill_match=round(skill_match, 2),
            experience_depth=round(experience_depth, 2),
            education_certs=round(education_certs, 2),
            format_completeness=round(format_completeness, 2),
        )

        logger.info(
            "Resume scored: total=%.1f, skills=%.1f, exp=%.1f, edu=%.1f, format=%.1f",
            total, breakdown.skill_match, breakdown.experience_depth,
            breakdown.education_certs, breakdown.format_completeness,
        )

        return ResumeScoreResponse(
            total_score=total,
            breakdown=breakdown,
            extracted_data=resume,
            tier=_assign_tier(total),
            processing_time_ms=elapsed_ms,
            cached=False,
            warnings=warnings,
        )

    except Exception as exc:
        logger.error("Resume scoring failed: %s", exc)
        raise ScoringError(f"Failed to score resume: {exc}") from exc
