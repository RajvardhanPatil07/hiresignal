"""Tests for the synthesis engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.models.schemas import (
    CandidateEvaluateRequest,
    CandidateEvaluateResponse,
    CandidateTier,
    TierAssignment,
)
from backend.synthesis.engine import (
    _derive_concerns,
    _derive_strengths,
    _get_next_steps,
    _template_conclusion,
    assign_tier,
    compute_weighted_total,
    evaluate_candidate,
)


class TestWeightedTotal:
    """Test weighted total score computation."""

    def test_equal_weights(self) -> None:
        """Test with default 60/40 weights."""
        result = compute_weighted_total(80.0, 70.0)
        expected = 80.0 * 0.6 + 70.0 * 0.4
        assert abs(result - expected) < 0.01

    def test_perfect_scores(self) -> None:
        """Test with perfect scores."""
        result = compute_weighted_total(100.0, 100.0)
        assert result == 100.0

    def test_zero_scores(self) -> None:
        """Test with zero scores."""
        result = compute_weighted_total(0.0, 0.0)
        assert result == 0.0

    def test_clamped_max(self) -> None:
        """Test score does not exceed 100."""
        result = compute_weighted_total(100.0, 100.0)
        assert result <= 100.0


class TestTierAssignment:
    """Test tier assignment logic."""

    def test_tier_1_threshold(self) -> None:
        """Test Tier 1 assignment at boundary."""
        tier = assign_tier(90.0)
        assert tier.tier == CandidateTier.TIER_1
        assert "Auto-advance" in tier.recommendation

    def test_tier_1_high(self) -> None:
        """Test Tier 1 with high score."""
        tier = assign_tier(95.0)
        assert tier.tier == CandidateTier.TIER_1

    def test_tier_2_boundary_low(self) -> None:
        """Test Tier 2 at lower boundary."""
        tier = assign_tier(75.0)
        assert tier.tier == CandidateTier.TIER_2

    def test_tier_2_boundary_high(self) -> None:
        """Test Tier 2 at upper boundary."""
        tier = assign_tier(89.0)
        assert tier.tier == CandidateTier.TIER_2
        assert "Human review" in tier.recommendation

    def test_tier_3_boundary_low(self) -> None:
        """Test Tier 3 at lower boundary."""
        tier = assign_tier(60.0)
        assert tier.tier == CandidateTier.TIER_3

    def test_tier_3_boundary_high(self) -> None:
        """Test Tier 3 at upper boundary."""
        tier = assign_tier(74.0)
        assert tier.tier == CandidateTier.TIER_3
        assert "gather more data" in tier.recommendation.lower()

    def test_reject_boundary(self) -> None:
        """Test Reject at boundary."""
        tier = assign_tier(59.0)
        assert tier.tier == CandidateTier.REJECT

    def test_reject_low(self) -> None:
        """Test Reject with very low score."""
        tier = assign_tier(10.0)
        assert tier.tier == CandidateTier.REJECT
        assert "Auto-reject" in tier.recommendation

    def test_reject_zero(self) -> None:
        """Test Reject with zero score."""
        tier = assign_tier(0.0)
        assert tier.tier == CandidateTier.REJECT


class TestTemplateConclusion:
    """Test template-based conclusion generation."""

    def test_tier_1_conclusion(self) -> None:
        """Test Tier 1 conclusion template."""
        req = CandidateEvaluateRequest(resume_score=90.0, social_score=90.0)
        tier = assign_tier(90.0)
        conclusion = _template_conclusion(req, 90.0, tier)

        assert "exceptional" in conclusion.lower() or "strong" in conclusion.lower()
        assert str(90.0) in conclusion

    def test_tier_2_conclusion(self) -> None:
        """Test Tier 2 conclusion template."""
        req = CandidateEvaluateRequest(resume_score=80.0, social_score=75.0)
        tier = assign_tier(80.0)
        conclusion = _template_conclusion(req, 80.0, tier)

        assert "human review" in conclusion.lower()

    def test_tier_3_conclusion(self) -> None:
        """Test Tier 3 conclusion template."""
        req = CandidateEvaluateRequest(resume_score=65.0, social_score=55.0)
        tier = assign_tier(65.0)
        conclusion = _template_conclusion(req, 65.0, tier)

        assert "additional" in conclusion.lower() or "gather more" in conclusion.lower()

    def test_reject_conclusion(self) -> None:
        """Test Reject conclusion template."""
        req = CandidateEvaluateRequest(resume_score=40.0, social_score=30.0)
        tier = assign_tier(40.0)
        conclusion = _template_conclusion(req, 40.0, tier)

        assert "does not" in conclusion.lower() or "rejection" in conclusion.lower()

    def test_conclusion_with_name(self) -> None:
        """Test conclusion includes candidate name."""
        req = CandidateEvaluateRequest(
            resume_score=85.0,
            social_score=80.0,
            candidate_name="Jane Smith",
            candidate_email="jane@example.com",
            job_title="Senior Engineer",
        )
        tier = assign_tier(83.0)
        conclusion = _template_conclusion(req, 83.0, tier)

        assert "Jane Smith" in conclusion


class TestStrengthsAndConcerns:
    """Test strengths and concerns derivation."""

    def test_strong_scores(self) -> None:
        """Test strengths from high scores."""
        strengths = _derive_strengths(85.0, 75.0)
        assert len(strengths) > 0
        assert any("resume" in s.lower() for s in strengths)

    def test_strong_social(self) -> None:
        """Test strengths from strong social score."""
        strengths = _derive_strengths(50.0, 80.0)
        assert any("social" in s.lower() or "github" in s.lower() for s in strengths)

    def test_no_strengths(self) -> None:
        """Test with very low scores."""
        strengths = _derive_strengths(10.0, 10.0)
        assert len(strengths) >= 1  # Should still have something

    def test_concerns_weak_resume(self) -> None:
        """Test concerns from weak resume."""
        concerns = _derive_concerns(40.0, 70.0)
        assert len(concerns) > 0
        assert any("resume" in c.lower() for c in concerns)

    def test_concerns_gap(self) -> None:
        """Test concerns from resume-social gap."""
        concerns = _derive_concerns(80.0, 20.0)
        assert len(concerns) > 0
        assert any("gap" in c.lower() or "online" in c.lower() for c in concerns)

    def test_no_concerns(self) -> None:
        """Test no concerns with strong scores."""
        concerns = _derive_concerns(90.0, 90.0)
        assert len(concerns) == 0


class TestNextSteps:
    """Test next steps recommendations."""

    def test_tier_1_next_steps(self) -> None:
        """Test Tier 1 next steps."""
        steps = _get_next_steps(CandidateTier.TIER_1)
        assert "interview" in steps.lower()

    def test_tier_2_next_steps(self) -> None:
        """Test Tier 2 next steps."""
        steps = _get_next_steps(CandidateTier.TIER_2)
        assert "human review" in steps.lower() or "recruiter" in steps.lower()

    def test_tier_3_next_steps(self) -> None:
        """Test Tier 3 next steps."""
        steps = _get_next_steps(CandidateTier.TIER_3)
        assert "assessment" in steps.lower() or "gather" in steps.lower()

    def test_reject_next_steps(self) -> None:
        """Test Reject next steps."""
        steps = _get_next_steps(CandidateTier.REJECT)
        assert "rejection" in steps.lower() or "feedback" in steps.lower()


class TestEvaluateCandidate:
    """Integration tests for the full evaluation pipeline."""

    @pytest.mark.asyncio
    async def test_evaluate_tier_1(self, candidate_eval_request: CandidateEvaluateRequest) -> None:
        """Test evaluation producing Tier 1 result."""
        req = CandidateEvaluateRequest(
            resume_score=92.0,
            social_score=88.0,
            candidate_name="Top Candidate",
            candidate_email="top@example.com",
            job_title="Senior Role",
        )

        result = await evaluate_candidate(req)

        assert result.report.weighted_total > 0
        assert result.report.tier.tier == CandidateTier.TIER_1
        assert result.report.conclusion
        assert result.processing_time_ms >= 0
        assert result.report.processed_at

    @pytest.mark.asyncio
    async def test_evaluate_tier_2(self, candidate_eval_request: CandidateEvaluateRequest) -> None:
        """Test evaluation producing Tier 2 result."""
        req = CandidateEvaluateRequest(
            resume_score=80.0,
            social_score=75.0,
            candidate_name="Good Candidate",
            candidate_email="good@example.com",
            job_title="Mid-Level Role",
        )

        result = await evaluate_candidate(req)

        assert result.report.tier.tier == CandidateTier.TIER_2
        assert result.report.strengths
        assert result.report.next_steps

    @pytest.mark.asyncio
    async def test_evaluate_reject(self, candidate_eval_request: CandidateEvaluateRequest) -> None:
        """Test evaluation producing Reject result."""
        req = CandidateEvaluateRequest(
            resume_score=40.0,
            social_score=30.0,
            candidate_name="Weak Candidate",
            candidate_email="weak@example.com",
            job_title="Junior Role",
        )

        result = await evaluate_candidate(req)

        assert result.report.tier.tier == CandidateTier.REJECT
        assert result.report.concerns

    @pytest.mark.asyncio
    async def test_evaluate_with_llm_conclusion(self) -> None:
        """Test evaluation with LLM-generated conclusion."""
        with patch("backend.core.config.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "test-key"
            mock_settings.return_value.LLM_MODEL = "gpt-4o-mini"

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.return_value = MagicMock(
                    status_code=200,
                    json=MagicMock(return_value={
                        "choices": [{
                            "message": {
                                "content": "This candidate shows strong technical skills and active community engagement, making them a solid fit for the role.",
                            },
                            "finish_reason": "stop",
                        }]
                    }),
                )

                req = CandidateEvaluateRequest(
                    resume_score=85.0,
                    social_score=80.0,
                    candidate_name="Jane Smith",
                    candidate_email="jane@example.com",
                    job_title="Senior Python Backend Engineer",
                )

                result = await evaluate_candidate(req)
                assert "strong" in result.report.conclusion.lower()


class TestScoreBoundaries:
    """Test boundary conditions for scoring."""

    def test_exact_90(self) -> None:
        """Test exact boundary at 90."""
        tier = assign_tier(90.0)
        assert tier.tier == CandidateTier.TIER_1

    def test_exact_75(self) -> None:
        """Test exact boundary at 75."""
        tier = assign_tier(75.0)
        assert tier.tier == CandidateTier.TIER_2

    def test_exact_60(self) -> None:
        """Test exact boundary at 60."""
        tier = assign_tier(60.0)
        assert tier.tier == CandidateTier.TIER_3

    def test_exact_59(self) -> None:
        """Test just below Tier 3 boundary."""
        tier = assign_tier(59.99)
        assert tier.tier == CandidateTier.REJECT

    def test_weighted_at_90(self) -> None:
        """Test weights produce exactly 90."""
        # 100*0.6 + 75*0.4 = 60 + 30 = 90
        result = compute_weighted_total(100.0, 75.0)
        assert abs(result - 90.0) < 0.01
        tier = assign_tier(result)
        assert tier.tier == CandidateTier.TIER_1
