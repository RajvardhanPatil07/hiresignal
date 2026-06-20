"""Synthesis engine that combines resume and social scores into final evaluation."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.core.config import get_settings
from backend.core.llm_provider import api_base_url, api_headers, api_key
from backend.core.exceptions import LLMError, ScoringError
from backend.models.schemas import (
    CandidateEvaluateRequest,
    CandidateEvaluateResponse,
    CandidateTier,
    FinalReport,
    TierAssignment,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier assignment logic
# ---------------------------------------------------------------------------

def compute_weighted_total(resume_score: float, social_score: float) -> float:
    """Compute weighted total score.

    Weights are configurable via settings:
    - Resume: 60% (default)
    - Social: 40% (default)

    Args:
        resume_score: Resume score (0-100).
        social_score: Social media score (0-100).

    Returns:
        Weighted total score (0-100).
    """
    settings = get_settings()
    resume_weight = settings.RESUME_WEIGHT
    social_weight = settings.SOCIAL_WEIGHT

    total = (resume_score * resume_weight) + (social_score * social_weight)
    return round(min(100.0, max(0.0, total)), 2)


def assign_tier(weighted_total: float) -> TierAssignment:
    """Assign tier based on weighted total score.

    Tiers:
        90-100: Tier 1 - Auto-advance to interview
        75-89:  Tier 2 - Human review required
        60-74:  Tier 3 - Conditional, gather more data
        <60:    Reject - Auto-reject with feedback

    Args:
        weighted_total: Weighted total score.

    Returns:
        TierAssignment with tier, label, and recommendation.
    """
    if weighted_total >= 90:
        return TierAssignment(
            tier=CandidateTier.TIER_1,
            label="Exceptional Candidate",
            recommendation="Auto-advance to interview stage",
            confidence=0.95,
        )
    elif weighted_total >= 75:
        return TierAssignment(
            tier=CandidateTier.TIER_2,
            label="Strong Candidate",
            recommendation="Human review required before proceeding",
            confidence=0.80,
        )
    elif weighted_total >= 60:
        return TierAssignment(
            tier=CandidateTier.TIER_3,
            label="Conditional Candidate",
            recommendation="Gather more data - consider technical screening or additional references",
            confidence=0.65,
        )
    else:
        return TierAssignment(
            tier=CandidateTier.REJECT,
            label="Does Not Meet Requirements",
            recommendation="Auto-reject with constructive feedback",
            confidence=0.90,
        )


async def generate_conclusion(
    request: CandidateEvaluateRequest,
    weighted_total: float,
    tier: TierAssignment,
) -> str:
    """Generate a human-readable conclusion paragraph via LLM.

    Falls back to template-based generation if LLM is unavailable.

    Args:
        request: Evaluation request with scores.
        weighted_total: Computed weighted total.
        tier: Assigned tier.

    Returns:
        Human-readable conclusion paragraph.
    """
    settings = get_settings()

    # Try LLM first
    if api_key(settings):
        try:
            return await _llm_conclusion(request, weighted_total, tier)
        except LLMError as exc:
            logger.warning("LLM conclusion generation failed: %s", exc)

    # Fallback: template-based conclusion
    return _template_conclusion(request, weighted_total, tier)


async def _llm_conclusion(
    request: CandidateEvaluateRequest,
    weighted_total: float,
    tier: TierAssignment,
) -> str:
    """Generate a conclusion using the configured LLM provider."""
    import httpx

    settings = get_settings()

    prompt = f"""You are an expert technical recruiter writing a candidate evaluation summary.

Candidate: {request.candidate_name or "Unnamed Candidate"} ({request.candidate_email})
Position: {request.job_title or "Unspecified Role"}

Scores:
- Resume Score: {request.resume_score}/100
- Social Media Score: {request.social_score}/100
- Weighted Total: {weighted_total}/100
- Tier: {tier.tier.value} - {tier.label}

Write a concise 3-4 sentence professional conclusion paragraph summarizing:
1. Overall assessment
2. Key strengths
3. Any concerns or areas for follow-up
4. Recommended next action

Tone: Professional, objective, actionable."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{api_base_url(settings)}/chat/completions",
            headers=api_headers(settings),
            json={
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": "You write concise, professional candidate evaluation summaries for hiring teams."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.5,
                "max_tokens": 300,
            },
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()


def _template_conclusion(
    request: CandidateEvaluateRequest,
    weighted_total: float,
    tier: TierAssignment,
) -> str:
    """Generate a template-based conclusion when LLM is unavailable."""
    name = request.candidate_name or "The candidate"
    job = request.job_title or "the position"

    conclusions: dict[CandidateTier, str] = {
        CandidateTier.TIER_1: (
            f"{name} presents an exceptional profile for {job} with a strong weighted score of {weighted_total}/100. "
            f"Both resume credentials and social media presence demonstrate outstanding technical depth and community engagement. "
            f"Key strengths include verified technical skills and consistent professional activity. "
            f"Recommendation: {tier.recommendation}."
        ),
        CandidateTier.TIER_2: (
            f"{name} is a strong candidate for {job} with a weighted score of {weighted_total}/100. "
            f"The resume demonstrates solid qualifications, and the social media analysis supports most technical claims. "
            f"A human review is recommended to assess cultural fit and discuss specific project experiences in depth. "
            f"Recommendation: {tier.recommendation}."
        ),
        CandidateTier.TIER_3: (
            f"{name} shows potential for {job} with a weighted score of {weighted_total}/100, but additional vetting is warranted. "
            f"Some technical claims require further verification, and the social media presence is limited. "
            f"Consider a technical screening or coding assessment to validate core competencies. "
            f"Recommendation: {tier.recommendation}."
        ),
        CandidateTier.REJECT: (
            f"{name} does not currently meet the requirements for {job}, with a weighted score of {weighted_total}/100. "
            f"Significant gaps exist between the resume claims and verifiable evidence. "
            f"We recommend providing constructive feedback and keeping the profile on file for future opportunities. "
            f"Recommendation: {tier.recommendation}."
        ),
    }

    return conclusions.get(tier.tier, conclusions[CandidateTier.REJECT])


def _derive_strengths(resume_score: float, social_score: float) -> list[str]:
    """Derive key strengths from scores."""
    strengths: list[str] = []
    if resume_score >= 70:
        strengths.append("Strong resume with relevant skills and experience")
    if resume_score >= 85:
        strengths.append("Excellent skill-to-job match")
    if social_score >= 70:
        strengths.append("Active social media presence with verified technical contributions")
    if social_score >= 50:
        strengths.append("GitHub profile supports technical claims")
    if resume_score >= 60 and social_score >= 50:
        strengths.append("Good overall alignment between stated and demonstrated capabilities")
    if not strengths:
        strengths.append("Profile submitted for review")
    return strengths


def _derive_concerns(resume_score: float, social_score: float) -> list[str]:
    """Derive concerns from scores."""
    concerns: list[str] = []
    if resume_score < 50:
        concerns.append("Resume does not strongly match job requirements")
    if social_score < 40:
        concerns.append("Limited social media presence makes verification difficult")
    if resume_score >= 70 and social_score < 40:
        concerns.append("Significant gap between resume claims and verifiable online presence")
    if resume_score < 60 and social_score < 40:
        concerns.append("Both resume and social profiles indicate skills gaps")
    return concerns


def _get_next_steps(tier: CandidateTier) -> str:
    """Get recommended next steps based on tier."""
    steps: dict[CandidateTier, str] = {
        CandidateTier.TIER_1: (
            "Schedule interview within 48 hours. Prepare technical deep-dive questions. "
            "Notify hiring manager of high-priority candidate."
        ),
        CandidateTier.TIER_2: (
            "Assign to recruiter for human review. Schedule 15-min screening call. "
            "Prepare follow-up questions on experience gaps."
        ),
        CandidateTier.TIER_3: (
            "Send technical assessment or coding challenge. Request portfolio or additional references. "
            "Re-evaluate after additional data is collected."
        ),
        CandidateTier.REJECT: (
            "Send personalized rejection email with feedback. Archive profile for 6 months. "
            "Consider for junior roles if skills are close."
        ),
    }
    return steps.get(tier, steps[CandidateTier.REJECT])


async def evaluate_candidate(
    request: CandidateEvaluateRequest,
) -> CandidateEvaluateResponse:
    """Evaluate a candidate by combining resume and social scores.

    Args:
        request: CandidateEvaluateRequest with both scores.

    Returns:
        CandidateEvaluateResponse with full evaluation report.

    Raises:
        ScoringError: If evaluation computation fails.
    """
    start = time.time()

    try:
        # Compute weighted total
        weighted_total = compute_weighted_total(request.resume_score, request.social_score)

        # Assign tier
        tier = assign_tier(weighted_total)

        # Generate conclusion
        conclusion = await generate_conclusion(request, weighted_total, tier)

        # Derive strengths and concerns
        strengths = _derive_strengths(request.resume_score, request.social_score)
        concerns = _derive_concerns(request.resume_score, request.social_score)
        next_steps = _get_next_steps(tier.tier)

        elapsed_ms = int((time.time() - start) * 1000)

        report = FinalReport(
            candidate_name=request.candidate_name,
            candidate_email=request.candidate_email,
            job_title=request.job_title,
            resume_score=request.resume_score,
            social_score=request.social_score,
            weighted_total=weighted_total,
            tier=tier,
            conclusion=conclusion,
            strengths=strengths,
            concerns=concerns,
            next_steps=next_steps,
            processed_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "Candidate evaluated: %s -> %.1f (%s) in %dms",
            request.candidate_email, weighted_total, tier.tier.value, elapsed_ms,
        )

        return CandidateEvaluateResponse(
            report=report,
            processing_time_ms=elapsed_ms,
            cached=False,
        )

    except Exception as exc:
        logger.error("Candidate evaluation failed: %s", exc)
        raise ScoringError(f"Evaluation failed: {exc}") from exc
