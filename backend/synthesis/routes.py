"""FastAPI routes for the synthesis engine module."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.core.auth import verify_api_key
from backend.core.cache import get_cached, set_cached
from backend.core.rate_limiter import check_rate_limit
from backend.models.schemas import CandidateEvaluateRequest, CandidateEvaluateResponse
from backend.synthesis.engine import evaluate_candidate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/candidate", tags=["Candidate Evaluation"])


@router.post(
    "/evaluate",
    response_model=CandidateEvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate candidate with combined scores",
    description=(
        "Combine resume score and social media score into a final weighted evaluation. "
        "Generates tier assignment, conclusion paragraph, and recommended next steps. "
        "Weights: 60% resume + 40% social (configurable)."
    ),
)
async def evaluate_candidate_endpoint(
    api_key: Annotated[str, Depends(verify_api_key)],
    request: CandidateEvaluateRequest,
) -> CandidateEvaluateResponse:
    """Evaluate a candidate using combined resume and social scores.

    Args:
        api_key: Validated via X-API-Key header.
        request: CandidateEvaluateRequest with scores.

    Returns:
        CandidateEvaluateResponse with full evaluation report.
    """
    # Rate limiting
    await check_rate_limit(api_key)

    # Build cache key
    cache_input = {
        "resume_score": request.resume_score,
        "social_score": request.social_score,
        "email": request.candidate_email,
        "name": request.candidate_name,
        "job": request.job_title,
    }

    # Check cache
    cached = await get_cached("candidate_eval", cache_input)
    if cached:
        logger.info("Returning cached evaluation for %s", request.candidate_email)
        return CandidateEvaluateResponse(**cached, cached=True)

    # Run evaluation
    logger.info(
        "Evaluating candidate %s: resume=%.1f, social=%.1f",
        request.candidate_email, request.resume_score, request.social_score,
    )
    result = await evaluate_candidate(request)

    # Cache result
    result_dict = result.model_dump()
    await set_cached("candidate_eval", cache_input, result_dict)

    return result


@router.get(
    "/health",
    summary="Synthesis module health check",
)
async def synthesis_health() -> dict[str, str]:
    """Check synthesis module health."""
    return {"status": "healthy", "module": "synthesis"}
