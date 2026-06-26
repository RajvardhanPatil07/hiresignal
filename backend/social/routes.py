"""FastAPI routes for the social media intelligence module."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.core.auth import verify_api_key
from backend.core.cache import get_cached, set_cached
from backend.core.rate_limiter import check_rate_limit
from backend.models.schemas import ProviderStatus, SocialAnalyzeRequest, SocialScoreResponse
from backend.social.agents import get_provider_statuses, run_social_analysis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/social", tags=["Social Media Intelligence"])
SOCIAL_CACHE_VERSION = "embedded-profile-links-v1"


@router.post(
    "/analyze",
    response_model=SocialScoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze candidate's social media presence",
    description=(
        "Fetch and analyze a candidate's GitHub, LinkedIn, and Twitter profiles. "
        "Uses LangGraph agent workflow with LLM synthesis for scoring. "
        "Returns a social_score (0-100) with tech verification and red flags."
    ),
)
async def analyze_social_endpoint(
    api_key: Annotated[str, Depends(verify_api_key)],
    request: SocialAnalyzeRequest,
) -> SocialScoreResponse:
    """Analyze social media profiles for a candidate.

    Args:
        api_key: Validated via X-API-Key header.
        request: SocialAnalyzeRequest with candidate details.

    Returns:
        SocialScoreResponse with social score and findings.
    """
    # Rate limiting
    await check_rate_limit(api_key)

    # Build cache key
    cache_input = {
        "version": SOCIAL_CACHE_VERSION,
        "github": request.github_username,
        "email": request.candidate_email,
        "name": request.candidate_name,
        "linkedin": request.linkedin_url,
        "twitter": request.twitter_handle,
        "profile_urls": sorted(request.profile_urls),
        "approved_profile_urls": sorted(request.approved_profile_urls),
        "rejected_profile_urls": sorted(request.rejected_profile_urls),
        "web_discovery_enabled": request.web_discovery_enabled,
        "firecrawl_enabled": request.firecrawl_enabled,
        "consent_confirmed": request.consent_confirmed,
        "skills": sorted(request.claimed_skills),
    }

    # Check cache
    cached = await get_cached("social_analysis", cache_input)
    if cached:
        logger.info("Returning cached social analysis for @%s", request.github_username)
        return SocialScoreResponse(**{**cached, "cached": True})

    # Run analysis
    logger.info(
        "Starting social analysis for @%s (skills=%d)",
        request.github_username, len(request.claimed_skills),
    )
    result = await run_social_analysis(request)

    # Cache result
    result_dict = result.model_dump()
    await set_cached("social_analysis", cache_input, result_dict)

    return result


@router.get(
    "/health",
    summary="Social module health check",
)
async def social_health() -> dict[str, str]:
    """Check social media module health."""
    return {"status": "healthy", "module": "social"}


@router.get(
    "/providers",
    response_model=list[ProviderStatus],
    summary="External evidence provider configuration status",
)
async def provider_status_endpoint(
    api_key: Annotated[str, Depends(verify_api_key)],
) -> list[ProviderStatus]:
    """Return masked provider configuration status for the dashboard."""
    await check_rate_limit(api_key)
    return get_provider_statuses()
