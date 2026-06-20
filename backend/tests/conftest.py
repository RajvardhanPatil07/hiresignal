"""pytest fixtures for HireSignal tests."""

from __future__ import annotations

import json
import os
from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.models.schemas import (
    CandidateEvaluateRequest,
    GitHubProfile,
    GitHubRepo,
    ParsedResume,
    ResumeScoreRequest,
    SocialAnalyzeRequest,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_API_KEY = "dev-api-key-change-in-production"

SAMPLE_JOB_DESCRIPTION = """
Senior Python Backend Engineer

We are looking for an experienced Python Backend Engineer to join our growing team.
You will be responsible for designing and implementing scalable APIs, working with
microservices architecture, and collaborating with cross-functional teams.

Required Skills:
- Python (5+ years)
- FastAPI or Django
- PostgreSQL and Redis
- Docker and Kubernetes
- AWS or GCP
- RESTful API design
- Unit testing and CI/CD

Nice to Have:
- Experience with LangChain or LangGraph
- Knowledge of vector databases (Qdrant, Pinecone)
- Background in machine learning or NLP
- Open source contributions

Qualifications:
- Bachelor's degree in Computer Science or related field
- 5+ years of professional backend development
- Strong problem-solving skills
- Excellent communication skills
"""

SAMPLE_RESUME_TEXT = """
Jane Smith
Email: jane.smith@example.com | Phone: +1-555-123-4567
GitHub: github.com/janesmith | LinkedIn: linkedin.com/in/janesmith

SUMMARY
Senior Backend Engineer with 7 years of experience building scalable APIs and
microservices. Passionate about clean code, system design, and open source.

SKILLS
Python, FastAPI, Django, PostgreSQL, Redis, Docker, Kubernetes, AWS, REST API,
Git, CI/CD, Pytest, LangChain, Docker Compose, Terraform, Prometheus, Grafana,
Microservices, System Design, SQL, NoSQL, Message Queues

EXPERIENCE

Senior Backend Engineer | TechCorp Inc. | Jan 2021 - Present
- Architected microservices platform serving 10M+ daily requests
- Reduced API latency by 60% through Redis caching and query optimization
- Led migration from monolith to Kubernetes-based microservices
- Technologies: Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS

Backend Engineer | StartupXYZ | Jun 2018 - Dec 2020
- Built REST APIs serving 500K+ users
- Implemented CI/CD pipelines reducing deployment time by 70%
- Mentored junior engineers and conducted code reviews
- Technologies: Python, Django, PostgreSQL, Docker, AWS

Junior Developer | WebStudio | Aug 2016 - May 2018
- Developed backend features for e-commerce platform
- Wrote unit tests achieving 90% code coverage
- Technologies: Python, Flask, MySQL, Git

EDUCATION
Bachelor of Science in Computer Science
University of Technology, 2016

CERTIFICATIONS
- AWS Certified Solutions Architect - Associate (2022)
- Certified Kubernetes Administrator (2021)
- Docker Certified Associate (2020)
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_key() -> str:
    """Return the test API key."""
    return TEST_API_KEY


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """Create a test client for the FastAPI app."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(api_key: str) -> dict[str, str]:
    """Return headers with API key authentication."""
    return {"X-API-Key": api_key}


@pytest.fixture
def sample_job_description() -> str:
    """Return a sample job description."""
    return SAMPLE_JOB_DESCRIPTION


@pytest.fixture
def sample_resume_text() -> str:
    """Return sample resume text."""
    return SAMPLE_RESUME_TEXT


@pytest.fixture
def parsed_resume() -> ParsedResume:
    """Return a pre-built ParsedResume for testing."""
    return ParsedResume(
        name="Jane Smith",
        email="jane.smith@example.com",
        phone="+1-555-123-4567",
        skills=[
            "python", "fastapi", "django", "postgresql", "redis",
            "docker", "kubernetes", "aws", "rest api", "git",
            "ci/cd", "pytest", "langchain", "docker compose",
            "terraform", "prometheus", "grafana", "microservices",
            "system design", "sql", "nosql", "message queues",
        ],
        experience=[
            {
                "company": "TechCorp Inc.",
                "title": "Senior Backend Engineer",
                "start_date": "2021",
                "end_date": "Present",
                "description": "Architected microservices platform serving 10M+ daily requests",
                "years": 3.5,
                "is_senior": True,
            },
            {
                "company": "StartupXYZ",
                "title": "Backend Engineer",
                "start_date": "2018",
                "end_date": "2020",
                "description": "Built REST APIs serving 500K+ users",
                "years": 2.5,
                "is_senior": False,
            },
            {
                "company": "WebStudio",
                "title": "Junior Developer",
                "start_date": "2016",
                "end_date": "2018",
                "description": "Developed backend features for e-commerce platform",
                "years": 2.0,
                "is_senior": False,
            },
        ],
        education=[
            {
                "institution": "University of Technology",
                "degree": "Bachelor of Science",
                "field": "Computer Science",
                "year": "2016",
                "is_relevant": True,
            },
        ],
        certifications=[
            {
                "name": "AWS Certified Solutions Architect - Associate",
                "issuer": "Amazon Web Services",
                "year": "2022",
                "is_relevant": True,
            },
            {
                "name": "Certified Kubernetes Administrator",
                "issuer": "CNCF",
                "year": "2021",
                "is_relevant": True,
            },
            {
                "name": "Docker Certified Associate",
                "issuer": "Docker",
                "year": "2020",
                "is_relevant": True,
            },
        ],
        raw_text=SAMPLE_RESUME_TEXT,
        sections_found=["summary", "skills", "experience", "education", "contact", "certifications"],
        parse_quality="good",
    )


@pytest.fixture
def resume_score_request(sample_job_description: str) -> ResumeScoreRequest:
    """Return a sample resume score request."""
    return ResumeScoreRequest(
        job_description=sample_job_description,
        github_username="janesmith",
    )


@pytest.fixture
def social_analyze_request() -> SocialAnalyzeRequest:
    """Return a sample social analyze request."""
    return SocialAnalyzeRequest(
        candidate_email="jane.smith@example.com",
        github_username="janesmith",
        linkedin_url="https://linkedin.com/in/janesmith",
        twitter_handle="@janesmith",
        claimed_skills=["python", "fastapi", "django", "docker", "kubernetes", "aws"],
    )


@pytest.fixture
def github_profile_mock() -> GitHubProfile:
    """Return a mock GitHub profile for testing."""
    return GitHubProfile(
        username="janesmith",
        public_repos=25,
        followers=150,
        following=80,
        bio="Senior Backend Engineer | Python enthusiast | Open source contributor",
        company="TechCorp Inc.",
        blog="https://janesmith.dev",
        location="San Francisco, CA",
        created_at="2015-06-15T00:00:00Z",
        repos=[
            GitHubRepo(
                name="fastapi-microservices",
                language="Python",
                stars=120,
                forks=30,
                description="Production-ready FastAPI microservices template",
                is_fork=False,
                updated_at="2024-01-15T00:00:00Z",
            ),
            GitHubRepo(
                name="redis-cache-lib",
                language="Python",
                stars=85,
                forks=15,
                description="High-performance Redis caching library",
                is_fork=False,
                updated_at="2024-01-10T00:00:00Z",
            ),
            GitHubRepo(
                name="k8s-deployment-tool",
                language="Go",
                stars=45,
                forks=10,
                description="Kubernetes deployment automation tool",
                is_fork=False,
                updated_at="2023-12-20T00:00:00Z",
            ),
        ],
        languages={"Python": 15, "Go": 5, "TypeScript": 3, "Shell": 2},
    )


@pytest.fixture
def mock_openai_embedding_response() -> dict[str, Any]:
    """Return a mock OpenAI embedding API response."""
    return {
        "object": "list",
        "data": [
            {
                "object": "embedding",
                "embedding": [0.1] * 1536,
                "index": 0,
            }
        ],
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 100, "total_tokens": 100},
    }


@pytest.fixture
def mock_openai_chat_response() -> dict[str, Any]:
    """Return a mock OpenAI chat completions response."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({
                        "social_score": 78.5,
                        "findings": {
                            "technical_depth": "Strong Python ecosystem expertise with diverse project portfolio",
                            "contribution_quality": "Well-documented repos with meaningful star counts",
                            "thought_leadership": "Active blog and consistent open source contributions",
                            "community_engagement": "150 followers, good engagement on technical content",
                            "activity_consistency": "Regular commits across multiple projects",
                        },
                        "tech_verification": {
                            "verified": ["python", "fastapi", "docker", "kubernetes"],
                            "unverified": ["django"],
                            "discrepancies": [],
                            "confidence": 0.85,
                        },
                        "red_flags": [],
                    }),
                },
                "finish_reason": "stop",
                "index": 0,
            }
        ],
        "usage": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
    }


@pytest.fixture
def mock_github_user_response() -> dict[str, Any]:
    """Return mock GitHub user API response."""
    return {
        "login": "janesmith",
        "public_repos": 25,
        "followers": 150,
        "following": 80,
        "bio": "Senior Backend Engineer | Python enthusiast",
        "company": "TechCorp Inc.",
        "blog": "https://janesmith.dev",
        "location": "San Francisco, CA",
        "created_at": "2015-06-15T00:00:00Z",
    }


@pytest.fixture
def mock_github_repos_response() -> list[dict[str, Any]]:
    """Return mock GitHub repos API response."""
    return [
        {
            "name": "fastapi-microservices",
            "language": "Python",
            "stargazers_count": 120,
            "forks_count": 30,
            "description": "Production-ready FastAPI microservices template",
            "fork": False,
            "updated_at": "2024-01-15T00:00:00Z",
        },
        {
            "name": "redis-cache-lib",
            "language": "Python",
            "stargazers_count": 85,
            "forks_count": 15,
            "description": "High-performance Redis caching library",
            "fork": False,
            "updated_at": "2024-01-10T00:00:00Z",
        },
        {
            "name": "k8s-deployment-tool",
            "language": "Go",
            "stargazers_count": 45,
            "forks_count": 10,
            "description": "Kubernetes deployment automation tool",
            "fork": False,
            "updated_at": "2023-12-20T00:00:00Z",
        },
    ]


@pytest.fixture
def candidate_eval_request() -> CandidateEvaluateRequest:
    """Return a sample candidate evaluation request."""
    return CandidateEvaluateRequest(
        resume_score=82.5,
        social_score=78.5,
        candidate_name="Jane Smith",
        candidate_email="jane.smith@example.com",
        job_title="Senior Python Backend Engineer",
    )
