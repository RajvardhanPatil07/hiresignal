"""Pydantic v2 schemas for HireSignal API requests and responses."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------

class CandidateTier(str, Enum):
    """Candidate quality tier based on combined score."""

    TIER_1 = "Tier 1"
    TIER_2 = "Tier 2"
    TIER_3 = "Tier 3"
    REJECT = "Reject"


class FileFormat(str, Enum):
    """Supported resume file formats."""

    PDF = "pdf"
    DOCX = "docx"


# ---------------------------------------------------------------------------
# Resume parsing
# ---------------------------------------------------------------------------

class ExperienceEntry(BaseModel):
    """A single work experience entry."""

    company: str = Field(default="", description="Employer name")
    title: str = Field(default="", description="Job title")
    start_date: str = Field(default="", description="Start date")
    end_date: str = Field(default="", description="End date or 'Present'")
    description: str = Field(default="", description="Role description")
    years: float = Field(default=0.0, description="Duration in years")
    is_senior: bool = Field(default=False, description="Senior-level role flag")


class EducationEntry(BaseModel):
    """A single education entry."""

    institution: str = Field(default="", description="School name")
    degree: str = Field(default="", description="Degree type")
    field: str = Field(default="", description="Field of study")
    year: str = Field(default="", description="Graduation year")
    is_relevant: bool = Field(default=False, description="Relevance to job")


class CertificationEntry(BaseModel):
    """A single certification entry."""

    name: str = Field(default="", description="Certification name")
    issuer: str = Field(default="", description="Issuing organization")
    year: str = Field(default="", description="Year obtained")
    is_relevant: bool = Field(default=False, description="Relevance to job")


class ParsedResume(BaseModel):
    """Structured resume data extracted from uploaded file."""

    name: str = Field(default="", description="Candidate full name")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")
    skills: list[str] = Field(default_factory=list, description="Technical skills")
    experience: list[ExperienceEntry] = Field(
        default_factory=list, description="Work history"
    )
    education: list[EducationEntry] = Field(
        default_factory=list, description="Education history"
    )
    certifications: list[CertificationEntry] = Field(
        default_factory=list, description="Professional certifications"
    )
    raw_text: str = Field(default="", description="Full extracted text")
    sections_found: list[str] = Field(
        default_factory=list, description="Sections detected in resume"
    )
    parse_quality: str = Field(
        default="good", description="Parsing quality: good/fair/poor"
    )


# ---------------------------------------------------------------------------
# Resume scoring
# ---------------------------------------------------------------------------

class ResumeScoreBreakdown(BaseModel):
    """Detailed scoring breakdown for resume evaluation."""

    skill_match: float = Field(
        default=0.0, ge=0, le=40, description="Skill match score (0-40)"
    )
    experience_depth: float = Field(
        default=0.0, ge=0, le=30, description="Experience depth score (0-30)"
    )
    education_certs: float = Field(
        default=0.0, ge=0, le=20, description="Education & certs score (0-20)"
    )
    format_completeness: float = Field(
        default=0.0, ge=0, le=10, description="Format & completeness score (0-10)"
    )


class ResumeScoreRequest(BaseModel):
    """Request body for resume scoring endpoint."""

    job_description: str = Field(
        ..., min_length=10, description="Full job description text"
    )
    github_username: Optional[str] = Field(
        default=None, description="GitHub username for cross-verification"
    )


class ResumeScoreResponse(BaseModel):
    """Response from resume scoring endpoint."""

    total_score: float = Field(ge=0, le=100, description="Total score 0-100")
    breakdown: ResumeScoreBreakdown = Field(description="Score breakdown")
    extracted_data: ParsedResume = Field(description="Parsed resume data")
    tier: CandidateTier = Field(description="Assigned tier")
    processing_time_ms: int = Field(description="Processing time in milliseconds")
    cached: bool = Field(default=False, description="Result served from cache")
    warnings: list[str] = Field(
        default_factory=list, description="Non-fatal warnings"
    )


# ---------------------------------------------------------------------------
# Social media intelligence
# ---------------------------------------------------------------------------

class GitHubRepo(BaseModel):
    """GitHub repository information."""

    name: str = Field(description="Repository name")
    language: Optional[str] = Field(default=None, description="Primary language")
    stars: int = Field(default=0, description="Star count")
    forks: int = Field(default=0, description="Fork count")
    description: Optional[str] = Field(default=None, description="Repo description")
    is_fork: bool = Field(default=False, description="Whether repo is a fork")
    updated_at: Optional[str] = Field(default=None, description="Last updated")


class GitHubProfile(BaseModel):
    """GitHub profile data."""

    username: str = Field(description="GitHub username")
    public_repos: int = Field(default=0, description="Number of public repos")
    followers: int = Field(default=0, description="Follower count")
    following: int = Field(default=0, description="Following count")
    bio: Optional[str] = Field(default=None, description="Profile bio")
    company: Optional[str] = Field(default=None, description="Company")
    blog: Optional[str] = Field(default=None, description="Blog URL")
    location: Optional[str] = Field(default=None, description="Location")
    created_at: Optional[str] = Field(default=None, description="Account creation date")
    repos: list[GitHubRepo] = Field(default_factory=list, description="Top repositories")
    languages: dict[str, int] = Field(
        default_factory=dict, description="Language usage counts"
    )


class LinkedInProfile(BaseModel):
    """LinkedIn profile data (when API key available)."""

    headline: Optional[str] = Field(default=None)
    summary: Optional[str] = Field(default=None)
    industry: Optional[str] = Field(default=None)
    positions: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    retrieved: bool = Field(default=False, description="Whether data was retrieved")


class TwitterProfile(BaseModel):
    """Twitter/X profile data (when API key available)."""

    description: Optional[str] = Field(default=None)
    followers_count: int = Field(default=0)
    tweet_count: int = Field(default=0)
    recent_tweets: list[str] = Field(default_factory=list)
    retrieved: bool = Field(default=False, description="Whether data was retrieved")


class TechVerification(BaseModel):
    """Technology claim verification results."""

    verified: list[str] = Field(default_factory=list, description="Verified skills")
    unverified: list[str] = Field(
        default_factory=list, description="Unverified skills"
    )
    discrepancies: list[str] = Field(
        default_factory=list, description="Claimed vs actual mismatches"
    )
    confidence: float = Field(
        default=0.0, ge=0, le=1, description="Verification confidence"
    )


class SocialScoreResponse(BaseModel):
    """Response from social media analysis endpoint."""

    social_score: float = Field(ge=0, le=100, description="Social score 0-100")
    github: GitHubProfile = Field(description="GitHub profile data")
    linkedin: LinkedInProfile = Field(description="LinkedIn profile data")
    twitter: TwitterProfile = Field(description="Twitter profile data")
    findings: dict[str, Any] = Field(
        default_factory=dict, description="LLM-generated findings"
    )
    tech_verification: TechVerification = Field(
        description="Tech stack verification results"
    )
    red_flags: list[str] = Field(
        default_factory=list, description="Identified concerns"
    )
    warnings: list[str] = Field(default_factory=list)
    processing_time_ms: int = Field(description="Processing time in milliseconds")
    cached: bool = Field(default=False)


class SocialAnalyzeRequest(BaseModel):
    """Request body for social media analysis endpoint."""

    candidate_email: str = Field(..., description="Candidate email address")
    github_username: str = Field(..., min_length=1, description="GitHub username")
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn profile URL")
    twitter_handle: Optional[str] = Field(default=None, description="Twitter/X handle")
    claimed_skills: list[str] = Field(
        default_factory=list, description="Skills from resume for verification"
    )

    @field_validator("github_username")
    @classmethod
    def validate_github_username(cls, v: str) -> str:
        """Strip @ prefix if present."""
        return v.lstrip("@")


# ---------------------------------------------------------------------------
# Synthesis engine
# ---------------------------------------------------------------------------

class CandidateEvaluateRequest(BaseModel):
    """Request body for candidate evaluation endpoint."""

    resume_score: float = Field(..., ge=0, le=100, description="Resume score")
    social_score: float = Field(..., ge=0, le=100, description="Social media score")
    candidate_name: str = Field(default="", description="Candidate name")
    candidate_email: str = Field(default="", description="Candidate email")
    job_title: str = Field(default="", description="Job title applied for")


class TierAssignment(BaseModel):
    """Tier assignment with recommendation."""

    tier: CandidateTier = Field(description="Assigned tier")
    label: str = Field(description="Human-readable tier label")
    recommendation: str = Field(description="Action recommendation")
    confidence: float = Field(ge=0, le=1, description="Confidence in assignment")


class FinalReport(BaseModel):
    """Complete candidate evaluation report."""

    candidate_name: str = Field(description="Candidate name")
    candidate_email: str = Field(description="Candidate email")
    job_title: str = Field(description="Job title")
    resume_score: float = Field(ge=0, le=100)
    social_score: float = Field(ge=0, le=100)
    weighted_total: float = Field(ge=0, le=100)
    tier: TierAssignment = Field(description="Tier assignment")
    conclusion: str = Field(description="Human-readable conclusion paragraph")
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    next_steps: str = Field(description="Recommended next steps")
    processed_at: str = Field(description="ISO timestamp")


class CandidateEvaluateResponse(BaseModel):
    """Response from candidate evaluation endpoint."""

    report: FinalReport = Field(description="Full evaluation report")
    processing_time_ms: int = Field()
    cached: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthStatus(BaseModel):
    """Health check response."""

    status: str = Field(description="Overall status: healthy/degraded/unhealthy")
    version: str = Field(description="App version")
    services: dict[str, str] = Field(
        default_factory=dict, description="Individual service statuses"
    )
    timestamp: str = Field(description="ISO timestamp")
