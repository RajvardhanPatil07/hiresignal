"""Tests for the social media intelligence module."""

from __future__ import annotations
from typing import Any

import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.schemas import GitHubProfile, GitHubRepo, ProfileEvidence, SocialAnalyzeRequest
from backend.social.agents import (
    _heuristic_social_score,
    AgentState,
    build_identity_match,
    build_score_breakdown,
    fetch_github,
    fetch_linkedin,
    fetch_twitter,
    synthesize,
)
from backend.social.evidence import (
    build_discovery_queries,
    discover_profile_urls_with_brave,
    fetch_public_profile,
    is_supported_profile_url,
    platform_from_url,
    profile_home_url,
    seed_profile_urls,
    username_from_url,
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

        class MockResponse:
            status_code: int
            _data: Any
            def __init__(self, status_code: int, data: Any):
                self.status_code = status_code
                self._data = data
            def json(self) -> Any:
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


class TestProfileEvidence:
    """Test public profile evidence discovery helpers."""

    def test_platform_and_username_detection(self) -> None:
        """Test supported platform URL parsing."""
        assert platform_from_url("https://huggingface.co/janesmith") == "huggingface"
        assert username_from_url("https://leetcode.com/u/janesmith", "leetcode") == "janesmith"
        assert username_from_url("https://codechef.com/users/janesmith", "codechef") == "janesmith"

    def test_seed_profile_urls_dedupes_sources(self) -> None:
        """Test seed URL construction from request, GitHub, and discovered links."""
        req = SocialAnalyzeRequest(
            candidate_email="test@example.com",
            github_username="janesmith",
            profile_urls=["github.com/janesmith", "huggingface.co/janesmith"],
        )
        github = GitHubProfile(username="janesmith", blog="https://linkedin.com/in/janesmith")
        urls = seed_profile_urls(req, github, ["https://huggingface.co/janesmith"])
        assert urls.count("https://github.com/janesmith") == 1
        assert "https://huggingface.co/janesmith" in urls
        assert "https://linkedin.com/in/janesmith" in urls

    def test_profile_url_validation_and_home_url(self) -> None:
        """Test search result URLs are filtered and canonicalized."""
        assert is_supported_profile_url("https://github.com/janesmith/project")
        assert not is_supported_profile_url("https://github.com/topics/python")
        assert profile_home_url("https://huggingface.co/models/janesmith/cool-model") == "https://huggingface.co/janesmith"
        assert profile_home_url("https://codechef.com/users/janesmith") == "https://www.codechef.com/users/janesmith"

    def test_build_discovery_queries_uses_name_and_profiles(self) -> None:
        """Test Brave discovery queries use available candidate identity."""
        req = SocialAnalyzeRequest(
            candidate_email="jane@example.com",
            candidate_name="Jane Smith",
            profile_urls=["https://github.com/janesmith"],
        )
        queries = build_discovery_queries(req, max_queries=4)
        joined = " ".join(queries)
        assert '"Jane Smith"' in joined
        assert "github" in joined.lower()
        assert len(queries) == 4

    @pytest.mark.asyncio
    async def test_discover_profile_urls_with_brave(self) -> None:
        """Test Brave Search discovery parses supported profile URLs."""
        req = SocialAnalyzeRequest(candidate_email="jane@example.com", candidate_name="Jane Smith")

        class MockResponse:
            status_code = 200
            def json(self) -> dict[str, Any]:
                return {
                    "web": {
                        "results": [
                            {
                                "url": "https://github.com/janesmith/project",
                                "title": "Jane Smith GitHub",
                                "description": "Hugging Face: https://huggingface.co/janesmith",
                            },
                            {
                                "url": "https://github.com/topics/python",
                                "title": "Ignore non-profile",
                                "description": "",
                            },
                        ]
                    }
                }
            def raise_for_status(self) -> None:
                pass

        settings_mock = MagicMock()
        settings_mock.WEB_DISCOVERY_ENABLED = True
        settings_mock.BRAVE_SEARCH_API_KEY = "brave-key"
        settings_mock.WEB_DISCOVERY_MAX_QUERIES = 1
        settings_mock.WEB_DISCOVERY_MAX_RESULTS = 5

        async def mock_get(url: str, **kwargs: Any) -> MockResponse:
            return MockResponse()

        with patch("backend.social.evidence.get_settings", return_value=settings_mock):
            with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
                async with httpx.AsyncClient() as client:
                    urls, evidence, warnings = await discover_profile_urls_with_brave(client, req, [])

        assert warnings == []
        assert "https://github.com/janesmith" in urls
        assert "https://huggingface.co/janesmith" in urls
        assert evidence is not None
        assert evidence.platform == "brave_search"

    @pytest.mark.asyncio
    async def test_fetch_public_profile_uses_firecrawl(self) -> None:
        """Test Firecrawl scrape output is converted into profile evidence."""
        settings_mock = MagicMock()
        settings_mock.FIRECRAWL_ENABLED = True
        settings_mock.FIRECRAWL_API_KEY = "fire-key"

        class MockResponse:
            status_code = 200
            def json(self) -> dict[str, Any]:
                return {
                    "success": True,
                    "data": {
                        "markdown": "Jane Smith has 120 problems solved with Python and Docker projects.",
                        "links": ["https://leetcode.com/u/janesmith"],
                        "metadata": {
                            "title": "Jane Smith | Kaggle",
                            "description": "Data scientist profile",
                            "sourceURL": "https://www.kaggle.com/janesmith",
                        },
                    },
                }
            def raise_for_status(self) -> None:
                pass

        async def mock_post(url: str, **kwargs: Any) -> MockResponse:
            return MockResponse()

        with patch("backend.social.evidence.get_settings", return_value=settings_mock):
            with patch.object(httpx.AsyncClient, "post", side_effect=mock_post):
                async with httpx.AsyncClient() as client:
                    item = await fetch_public_profile(client, "https://www.kaggle.com/janesmith", "kaggle")

        assert item.retrieved is True
        assert item.metrics["source"] == "firecrawl"
        assert item.metrics["solved"] == 120
        assert "python" in item.skills
        assert "https://leetcode.com/u/janesmith" in item.links


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
                def json(self) -> Any:
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
                def json(self) -> Any:
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

    def test_score_breakdown_and_identity_match(self) -> None:
        """Test transparent score and identity summaries."""
        req = SocialAnalyzeRequest(
            candidate_email="janesmith@example.com",
            candidate_name="Jane Smith",
            github_username="janesmith",
            claimed_skills=["python", "docker"],
        )
        state = AgentState(request=req)
        state.github = GitHubProfile(
            username="janesmith",
            public_repos=8,
            followers=10,
            languages={"Python": 4},
            repos=[GitHubRepo(name="api", language="Python", stars=12)],
        )
        state.profile_evidence = [
            ProfileEvidence(
                platform="github",
                url="https://github.com/janesmith",
                username="janesmith",
                retrieved=True,
                summary="Jane Smith public repos",
                skills=["Python"],
                confidence=0.9,
            )
        ]
        state.tech_verification.verified = ["python"]
        state.tech_verification.confidence = 0.6
        identity = build_identity_match(req, state.github, state.profile_evidence)
        breakdown = build_score_breakdown(state, identity)

        assert identity.score > 0
        assert breakdown.components
        assert breakdown.total >= 0
