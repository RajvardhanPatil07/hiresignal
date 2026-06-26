"""API integration tests for HireSignal endpoints."""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.models.schemas import SocialAnalyzeRequest


# ---------------------------------------------------------------------------
# Health Endpoint Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_check(self, client: TestClient) -> None:
        """Test basic health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "services" in data

    def test_readiness_probe(self, client: TestClient) -> None:
        """Test readiness probe."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_liveness_probe(self, client: TestClient) -> None:
        """Test liveness probe."""
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_root_endpoint(self, client: TestClient) -> None:
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

class TestAuthentication:
    """Test API key authentication."""

    def test_missing_api_key(self, client: TestClient) -> None:
        """Test request without API key is rejected on protected endpoints."""
        response = client.post(
            "/api/v1/candidate/evaluate",
            json={"resume_score": 50, "social_score": 50},
        )
        assert response.status_code == 401

    def test_invalid_api_key(self, client: TestClient) -> None:
        """Test request with invalid API key is rejected."""
        response = client.post(
            "/api/v1/candidate/evaluate",
            headers={"X-API-Key": "wrong-key"},
            json={"resume_score": 50, "social_score": 50},
        )
        assert response.status_code == 401

    def test_valid_api_key(self, client: TestClient, auth_headers: dict) -> None:
        """Test request with valid API key succeeds."""
        response = client.get(
            "/api/v1/resume/health",
            headers=auth_headers,
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Resume Endpoint Tests
# ---------------------------------------------------------------------------

class TestResumeEndpoints:
    """Test resume scoring endpoints."""

    def test_resume_health(self, client: TestClient, auth_headers: dict) -> None:
        """Test resume module health."""
        response = client.get(
            "/api/v1/resume/health",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["module"] == "resume"

    @pytest.mark.asyncio
    async def test_score_resume_pdf_mock(
        self,
        client: TestClient,
        auth_headers: dict,
        sample_job_description: str,
        mock_openai_embedding_response: dict,
    ) -> None:
        """Test resume scoring with mocked PDF and embeddings."""
        # Create a minimal PDF-like content (not a real PDF, will fail parsing gracefully)
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"

        with patch("backend.resume.parser.pdfplumber.open") as mock_pdf:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = """
Jane Smith
jane.smith@example.com | 555-123-4567

SUMMARY
Senior Backend Engineer with 7 years of experience.

SKILLS
Python, FastAPI, Docker, Kubernetes, AWS, PostgreSQL, Redis

EXPERIENCE
Senior Backend Engineer | TechCorp | 2021 - Present
Built scalable APIs using Python and FastAPI.

EDUCATION
BS Computer Science | University of Technology | 2016

CERTIFICATIONS
AWS Certified Solutions Architect
"""
            mock_pdf.return_value.__enter__.return_value.pages = [mock_page]

            with patch("backend.resume.scorer._get_embedding", new_callable=AsyncMock) as mock_embed:
                mock_embed.side_effect = [
                    [0.1] * 1536,
                    [0.12] * 1536,
                ]

                response = client.post(
                    "/api/v1/resume/score",
                    headers=auth_headers,
                    data={"job_description": sample_job_description, "github_username": "janesmith"},
                    files={"resume_file": ("test_resume.pdf", BytesIO(pdf_content), "application/pdf")},
                )

                assert response.status_code == 200
                data = response.json()
                assert "total_score" in data
                assert "breakdown" in data
                assert "tier" in data
                assert "extracted_data" in data
                assert 0 <= data["total_score"] <= 100

    @pytest.mark.asyncio
    async def test_score_resume_docx_mock(
        self,
        client: TestClient,
        auth_headers: dict,
        sample_job_description: str,
    ) -> None:
        """Test resume scoring with mocked DOCX."""
        docx_content = b"PK\x03\x04 fake docx content"

        with patch("backend.resume.parser.Document") as mock_docx:
            mock_para = MagicMock()
            mock_para.text = "Python Developer with 5 years experience. Skills: Python, Django, Docker."
            mock_docx.return_value.paragraphs = [mock_para]

            response = client.post(
                "/api/v1/resume/score",
                headers=auth_headers,
                data={"job_description": sample_job_description[:200]},
                files={"resume_file": ("test_resume.docx", BytesIO(docx_content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )

            assert response.status_code == 200
            data = response.json()
            assert "total_score" in data

    def test_score_resume_no_file(
        self,
        client: TestClient,
        auth_headers: dict,
        sample_job_description: str,
    ) -> None:
        """Test resume scoring without file fails."""
        response = client.post(
            "/api/v1/resume/score",
            headers=auth_headers,
            data={"job_description": sample_job_description},
        )
        assert response.status_code == 422  # Missing required file

    def test_score_resume_invalid_extension(
        self,
        client: TestClient,
        auth_headers: dict,
        sample_job_description: str,
    ) -> None:
        """Test resume scoring with invalid file extension."""
        response = client.post(
            "/api/v1/resume/score",
            headers=auth_headers,
            data={"job_description": sample_job_description},
            files={"resume_file": ("resume.txt", BytesIO(b"text content"), "text/plain")},
        )
        assert response.status_code == 400

    def test_score_resume_short_jd(
        self,
        client: TestClient,
        auth_headers: dict,
    ) -> None:
        """Test resume scoring with short job description fails validation."""
        response = client.post(
            "/api/v1/resume/score",
            headers=auth_headers,
            data={"job_description": "short"},
            files={"resume_file": ("resume.pdf", BytesIO(b"%PDF test"), "application/pdf")},
        )
        assert response.status_code == 422  # Min length validation


# ---------------------------------------------------------------------------
# Social Endpoint Tests
# ---------------------------------------------------------------------------

class TestSocialEndpoints:
    """Test social media intelligence endpoints."""

    def test_social_health(self, client: TestClient, auth_headers: dict) -> None:
        """Test social module health."""
        response = client.get(
            "/api/v1/social/health",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["module"] == "social"

    def test_social_provider_status(self, client: TestClient, auth_headers: dict) -> None:
        """Test provider status endpoint."""
        response = client.get(
            "/api/v1/social/providers",
            headers=auth_headers,
        )
        assert response.status_code == 200
        providers = {item["provider"]: item for item in response.json()}
        assert "GitHub" in providers
        assert "Firecrawl" in providers

    @pytest.mark.asyncio
    async def test_analyze_social_mock(
        self,
        client: TestClient,
        auth_headers: dict,
        mock_github_user_response: dict,
        mock_github_repos_response: list[dict],
        mock_openai_chat_response: dict,
    ) -> None:
        """Test social analysis with mocked external APIs."""
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.side_effect = [
                MagicMock(status_code=200, json=MagicMock(return_value=mock_github_user_response)),
                MagicMock(status_code=200, json=MagicMock(return_value=mock_github_repos_response)),
            ]

            with patch("httpx.AsyncClient.post") as mock_post:
                mock_post.return_value = MagicMock(
                    status_code=200,
                    json=MagicMock(return_value=mock_openai_chat_response),
                )

                with patch("backend.core.config.get_settings") as mock_settings:
                    mock_settings.return_value.OPENAI_API_KEY = "test-key"
                    mock_settings.return_value.LLM_MODEL = "gpt-4o-mini"
                    mock_settings.return_value.LINKEDIN_API_KEY = None
                    mock_settings.return_value.TWITTER_BEARER_TOKEN = None

                    response = client.post(
                        "/api/v1/social/analyze",
                        headers=auth_headers,
                        json={
                            "candidate_email": "jane@example.com",
                            "github_username": "janesmith",
                            "claimed_skills": ["python", "fastapi", "docker"],
                        },
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert "social_score" in data
                    assert "github" in data
                    assert "findings" in data
                    assert "tech_verification" in data
                    assert "red_flags" in data
                    assert 0 <= data["social_score"] <= 100

    def test_analyze_social_validation(self, client: TestClient, auth_headers: dict) -> None:
        """Test social analysis request validation."""
        # Missing all profile sources
        response = client.post(
            "/api/v1/social/analyze",
            headers=auth_headers,
            json={
                "candidate_email": "jane@example.com",
            },
        )
        assert response.status_code == 422

        req = SocialAnalyzeRequest(
            candidate_email="jane@example.com",
            profile_urls=["https://huggingface.co/janesmith"],
        )
        assert req.profile_urls == ["https://huggingface.co/janesmith"]

        name_only_req = SocialAnalyzeRequest(
            candidate_email="jane@example.com",
            candidate_name="Jane Smith",
        )
        assert name_only_req.candidate_name == "Jane Smith"

    def test_analyze_social_github_strip_at(self, client: TestClient, auth_headers: dict) -> None:
        """Test that @ prefix is stripped from GitHub username."""
        with patch("backend.social.agents.fetch_github") as mock_fetch:
            mock_fetch.return_value = AsyncMock()

            # Just test the request validation/parsing
            req_data = {
                "candidate_email": "jane@example.com",
                "github_username": "@janesmith",
            }
            # The validator should strip the @
            from backend.models.schemas import SocialAnalyzeRequest
            req = SocialAnalyzeRequest(**req_data)
            assert req.github_username == "janesmith"


# ---------------------------------------------------------------------------
# Synthesis Endpoint Tests
# ---------------------------------------------------------------------------

class TestSynthesisEndpoints:
    """Test candidate evaluation endpoints."""

    def test_synthesis_health(self, client: TestClient, auth_headers: dict) -> None:
        """Test synthesis module health."""
        response = client.get(
            "/api/v1/candidate/health",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["module"] == "synthesis"

    def test_evaluate_candidate(self, client: TestClient, auth_headers: dict) -> None:
        """Test candidate evaluation endpoint."""
        response = client.post(
            "/api/v1/candidate/evaluate",
            headers=auth_headers,
            json={
                "resume_score": 82.5,
                "social_score": 78.5,
                "candidate_name": "Jane Smith",
                "candidate_email": "jane@example.com",
                "job_title": "Senior Python Backend Engineer",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "report" in data
        report = data["report"]
        assert "weighted_total" in report
        assert "tier" in report
        assert "conclusion" in report
        assert "strengths" in report
        assert "next_steps" in report
        assert "processed_at" in report
        assert 0 <= report["weighted_total"] <= 100

    def test_evaluate_candidate_validation(self, client: TestClient, auth_headers: dict) -> None:
        """Test candidate evaluation validation."""
        # Score out of range
        response = client.post(
            "/api/v1/candidate/evaluate",
            headers=auth_headers,
            json={
                "resume_score": 150,  # Invalid: > 100
                "social_score": 78.5,
            },
        )
        assert response.status_code == 422

    def test_evaluate_tier_1(self, client: TestClient, auth_headers: dict) -> None:
        """Test evaluation returning Tier 1."""
        response = client.post(
            "/api/v1/candidate/evaluate",
            headers=auth_headers,
            json={
                "resume_score": 95.0,
                "social_score": 90.0,
                "candidate_name": "Top Candidate",
                "candidate_email": "top@example.com",
                "job_title": "Senior Role",
            },
        )

        assert response.status_code == 200
        report = response.json()["report"]
        assert report["tier"]["tier"] == "Tier 1"
        assert "Auto-advance" in report["tier"]["recommendation"]

    def test_evaluate_reject(self, client: TestClient, auth_headers: dict) -> None:
        """Test evaluation returning Reject."""
        response = client.post(
            "/api/v1/candidate/evaluate",
            headers=auth_headers,
            json={
                "resume_score": 40.0,
                "social_score": 35.0,
                "candidate_name": "Weak Candidate",
                "candidate_email": "weak@example.com",
                "job_title": "Junior Role",
            },
        )

        assert response.status_code == 200
        report = response.json()["report"]
        assert report["tier"]["tier"] == "Reject"
        assert len(report["concerns"]) > 0


# ---------------------------------------------------------------------------
# OpenAPI / Docs Tests
# ---------------------------------------------------------------------------

class TestOpenAPI:
    """Test OpenAPI schema and documentation."""

    def test_openapi_json(self, client: TestClient) -> None:
        """Test OpenAPI schema is accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert "/api/v1/resume/score" in schema["paths"]
        assert "/api/v1/social/analyze" in schema["paths"]
        assert "/api/v1/candidate/evaluate" in schema["paths"]

    def test_docs_endpoint(self, client: TestClient) -> None:
        """Test Swagger UI docs endpoint."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()
