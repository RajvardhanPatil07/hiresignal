"""FastAPI routes for the resume scoring module."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from backend.core.auth import verify_api_key
from backend.core.cache import get_cached, set_cached
from backend.core.rate_limiter import check_rate_limit
from backend.core.exceptions import FileValidationError, ResumeParsingError
from backend.models.schemas import ResumeScoreRequest, ResumeScoreResponse
from backend.resume.parser import parse_resume
from backend.resume.scorer import score_resume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resume", tags=["Resume Scoring"])


@router.post(
    "/score",
    response_model=ResumeScoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Score a resume against a job description",
    description=(
        "Upload a PDF or DOCX resume along with a job description. "
        "Returns a structured score (0-100) with detailed breakdown, "
        "extracted resume data, and candidate tier assignment."
    ),
)
async def score_resume_endpoint(
    api_key: Annotated[str, Depends(verify_api_key)],
    job_description: Annotated[str, Form(..., min_length=10)],
    resume_file: Annotated[UploadFile, File(...)],
    github_username: Annotated[str | None, Form()] = None,
) -> ResumeScoreResponse:
    """Score an uploaded resume against the provided job description.

    Args:
        api_key: Validated via X-API-Key header dependency.
        job_description: Full job description text (form field).
        resume_file: PDF or DOCX resume file.
        github_username: Optional GitHub username for cross-verification.

    Returns:
        ResumeScoreResponse with score, breakdown, and parsed data.
    """
    # Rate limiting
    await check_rate_limit(api_key)

    # Validate filename
    if not resume_file.filename:
        raise FileValidationError("Resume file must have a filename")

    # Read file content
    content = await resume_file.read()
    if not content:
        raise FileValidationError("Resume file is empty")

    # Build cache key
    cache_input = {
        "filename": resume_file.filename,
        "content_hash": hash(content) & 0xFFFFFFFF,
        "job_description": job_description[:500],
        "github": github_username,
    }

    # Check cache
    cached = await get_cached("resume_score", cache_input)
    if cached:
        logger.info("Returning cached resume score for %s", resume_file.filename)
        return ResumeScoreResponse(**cached, cached=True)

    # Parse resume
    logger.info("Parsing resume: %s (%d bytes)", resume_file.filename, len(content))
    parsed = await parse_resume(resume_file.filename, content)

    # Score
    logger.info("Scoring resume against job description (%d chars)", len(job_description))
    result = await score_resume(parsed, job_description)

    # Cache result
    result_dict = result.model_dump()
    await set_cached("resume_score", cache_input, result_dict)

    return result


@router.get(
    "/health",
    summary="Resume module health check",
)
async def resume_health() -> dict[str, str]:
    """Check resume module health."""
    return {"status": "healthy", "module": "resume"}
