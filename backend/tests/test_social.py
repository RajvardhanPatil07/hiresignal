"""Tests for the social media intelligence module."""

from __future__ import annotations
from typing import Any

import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.schemas import GitHubProfile, GitHubRepo, SocialAnalyzeRequest
from backend.social.agents import (
    _heuristic_social_score,
    AgentState,
    fetch_github,
    fetch_linkedin,
    fetch_twitter,
    synthesize,
)


class TestFetchGitHub:
    """Test GitHub data fetching."""

    @pytest.mark.asyncio
    async def test_fetch_github_success(
        self,
        social_analyze_request: SocialAnalyzeRequest,
        mock_github_user_response: dict,
        mock_github_repos_response: list[dict],
    ) -> None:
        """Test successful GitHub profile fetch."""
        state = AgentState(request=social_analyze_request)

        call_count = 0
        async def mock_json():
            nonlocal call_count
            call_count += 1
            return mock_github_user_response if call_count == 1 else mock_github_repos_response

        class MockResponse:
            status_code: int
            _data: Any
            def __init__(self, status_code: int, data: Any):
                self.status_code = status_code
                self._data = data
            async def json(self) -> Any:
                return self._data
            def raise_for_status(self) -> None:
                pass

        # Patch the method on the class so async context manager picks it up
        async def mock_get(url: str, **kwargs: Any) -> MockResponse:
            if "repos" in url:
                return MockResponse(200, mock_github_repos_response)
            return MockResponse(200, mock_github_user_response)

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            result = await fetch_github(state)

            assert result.github.username == "janesmith"
            assert result.github.public_repos == 25
            assert result.github.followers == 150

    @pytest.mark.asyncio
    async def test_fetch_github_404(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test GitHub user not found."""
        state = AgentState(request=social_analyze_request)

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = AsyncMock(status_code=404)
            result = await fetch_github(state)

            assert result.github.username == "janesmith"
            assert result.github.public_repos == 0
            assert "not found" in result.warnings[0].lower()

    @pytest.mark.asyncio
    async def test_fetch_github_rate_limit(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test GitHub rate limit handling."""
        state = AgentState(request=social_analyze_request)

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = AsyncMock(status_code=403)
            result = await fetch_github(state)

            assert "rate limit" in result.warnings[0].lower()


class TestFetchLinkedIn:
    """Test LinkedIn data fetching."""

    @pytest.mark.asyncio
    async def test_fetch_linkedin_no_api_key(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test LinkedIn skipped when no API key."""
        with patch("backend.social.agents.get_settings") as mock_settings:
            mock_settings.return_value.LINKEDIN_API_KEY = None

            state = AgentState(request=social_analyze_request)
            result = await fetch_linkedin(state)

            assert result.linkedin.retrieved is False
            assert any("not configured" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_fetch_linkedin_no_url(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test LinkedIn skipped when no URL provided."""
        with patch("backend.social.agents.get_settings") as mock_settings:
            mock_settings.return_value.LINKEDIN_API_KEY = "test-key"

            req = SocialAnalyzeRequest(
                candidate_email="test@example.com",
                github_username="test",
                linkedin_url=None,
            )
            state = AgentState(request=req)
            result = await fetch_linkedin(state)

            assert result.linkedin.retrieved is False


class TestFetchTwitter:
    """Test Twitter data fetching."""

    @pytest.mark.asyncio
    async def test_fetch_twitter_no_token(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test Twitter skipped when no bearer token."""
        with patch("backend.social.agents.get_settings") as mock_settings:
            mock_settings.return_value.TWITTER_BEARER_TOKEN = None

            state = AgentState(request=social_analyze_request)
            result = await fetch_twitter(state)

            assert result.twitter.retrieved is False
            assert any("not configured" in w.lower() for w in result.warnings)

    @pytest.mark.asyncio
    async def test_fetch_twitter_no_handle(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test Twitter skipped when no handle provided."""
        with patch("backend.social.agents.get_settings") as mock_settings:
            mock_settings.return_value.TWITTER_BEARER_TOKEN = "test-token"

            req = SocialAnalyzeRequest(
                candidate_email="test@example.com",
                github_username="test",
                twitter_handle=None,
            )
            state = AgentState(request=req)
            result = await fetch_twitter(state)

            assert result.twitter.retrieved is False


class TestSynthesis:
    """Test LLM synthesis node."""

    @pytest.mark.asyncio
    async def test_synthesize_with_llm(
        self,
        social_analyze_request: SocialAnalyzeRequest,
        mock_openai_chat_response: dict,
    ) -> None:
        """Test synthesis with successful LLM call."""
        state = AgentState(request=social_analyze_request)
        state.github = GitHubProfile(
            username="janesmith",
            public_repos=25,
            followers=150,
            languages={"Python": 15, "Go": 5},
            repos=[
                GitHubRepo(name="repo1", language="Python", stars=100),
                GitHubRepo(name="repo2", language="Go", stars=50),
            ],
        )

        settings_mock = MagicMock()
        settings_mock.OPENAI_API_KEY = "test-key"
        settings_mock.LLM_MODEL = "gpt-4o-mini"

        with patch("backend.social.agents.get_settings", return_value=settings_mock):
            class MockResponse:
                status_code = 200
                async def json(self) -> Any:
                    return mock_openai_chat_response
                def raise_for_status(self) -> None:
                    pass

            async def mock_post(url: str, **kwargs: Any) -> MockResponse:
                return MockResponse()

            with patch.object(httpx.AsyncClient, "post", side_effect=mock_post):
                result = await synthesize(state)

                assert result.social_score > 0
                assert result.tech_verification.confidence > 0
                assert isinstance(result.red_flags, list)

    @pytest.mark.asyncio
    async def test_synthesize_no_api_key(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test synthesis falls back to heuristic when no API key."""
        settings_mock = MagicMock()
        settings_mock.OPENAI_API_KEY = ""
        settings_mock.LLM_MODEL = "gpt-4o-mini"

        with patch("backend.social.agents.get_settings", return_value=settings_mock):
            state = AgentState(request=social_analyze_request)
            state.github = GitHubProfile(
                username="janesmith",
                public_repos=10,
                followers=50,
                languages={"Python": 5},
                repos=[GitHubRepo(name="repo1", language="Python", stars=20)],
            )

            result = await synthesize(state)

            assert result.social_score >= 0
            # No warnings expected when heuristic fallback succeeds cleanly

    @pytest.mark.asyncio
    async def test_synthesize_invalid_json_response(
        self,
        social_analyze_request: SocialAnalyzeRequest,
    ) -> None:
        """Test synthesis handles invalid JSON from LLM."""
        settings_mock = MagicMock()
        settings_mock.OPENAI_API_KEY = "test-key"
        settings_mock.LLM_MODEL = "gpt-4o-mini"

        with patch("backend.social.agents.get_settings", return_value=settings_mock):
            state = AgentState(request=social_analyze_request)
            state.github = GitHubProfile(
                username="janesmith",
                public_repos=5,
                languages={"Python": 3},
            )

            bad_response = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": "This is not valid JSON!",
                    },
                    "finish_reason": "stop",
                }]
            }

            class MockResponse:
                status_code = 200
                async def json(self) -> Any:
                    return bad_response
                def raise_for_status(self) -> None:
                    pass

            async def mock_post(url: str, **kwargs: Any) -> MockResponse:
                return MockResponse()

            with patch.object(httpx.AsyncClient, "post", side_effect=mock_post):
                result = await synthesize(state)

                assert result.social_score >= 0
                assert any("invalid json" in w.lower() or "fallback" in w.lower()
                          for w in result.warnings)


class TestHeuristicScoring:
    """Test heuristic social score computation."""

    def test_heuristic_strong_profile(self, social_analyze_request: SocialAnalyzeRequest) -> None:
        """Test heuristic scoring for a strong profile."""
        state = AgentState(request=social_analyze_request)
        state.github = GitHubProfile(
            username="strongdev",
            public_repos=30,
            followers=500,
            created_at="2015-01-01T00:00:00Z",
            languages={"Python": 20, "Go": 5, "TypeScript": 5},
            repos=[
                GitHubRepo(name="popular", language="Python", stars=200),
                GitHubRepo(name="another", language="Go", stars=100),
            ],
        )

        result = _heuristic_social_score(state)
        assert result.social_score > 50

    def test_heuristic_weak_profile(self, social_analyze_request: SocialAnalyzeRequest) -> None:
        """Test heuristic scoring for a weak profile."""
        state = AgentState(request=social_analyze_request)
        state.github = GitHubProfile(
            username="newbie",
            public_repos=2,
            followers=0,
            languages={},
            repos=[],
        )

        result = _heuristic_social_score(state)
        assert result.social_score < 30

    def test_heuristic_no_claimed_skills(self) -> None:
        """Test heuristic when no skills are claimed."""
        req = SocialAnalyzeRequest(
            candidate_email="test@example.com",
            github_username="test",
            claimed_skills=[],
        )
        state = AgentState(request=req)
        state.github = GitHubProfile(
            username="test",
            public_repos=10,
            languages={"Python": 5, "JavaScript": 3},
        )

        result = _heuristic_social_score(state)
        assert result.social_score >= 0
