"""Pydantic v2 schemas for HireSignal API requests and responses."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    profile_urls: list[str] = Field(
        default_factory=list,
        description="Candidate-provided public profile URLs found in the resume",
    )
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
    twitter_username: Optional[str] = Field(default=None, description="GitHub-linked Twitter/X username")
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


class ProfileEvidence(BaseModel):
    """Evidence collected from a public candidate profile or portfolio URL."""

    platform: str = Field(description="Detected platform, such as github or huggingface")
    url: str = Field(description="Public URL analyzed")
    username: Optional[str] = Field(default=None, description="Username or profile slug")
    retrieved: bool = Field(default=False, description="Whether profile data was fetched")
    summary: str = Field(default="", description="Short evidence summary")
    metrics: dict[str, Any] = Field(default_factory=dict, description="Platform-specific public metrics")
    skills: list[str] = Field(default_factory=list, description="Skills or technologies inferred from public evidence")
    links: list[str] = Field(default_factory=list, description="Additional public links discovered on the profile")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal collection issues")
    confidence: float = Field(default=0.0, ge=0, le=1, description="Confidence that evidence belongs to the candidate")
    source_type: str = Field(default="public_api", description="Collection method: public_api, firecrawl, direct_http, search, skipped")
    citation: str = Field(default="", description="Short human-readable proof extracted from this source")


class EvidenceCitation(BaseModel):
    """Reader-facing citation for an evidence claim."""

    platform: str = Field(description="Evidence platform")
    url: str = Field(description="Source URL")
    label: str = Field(description="Short proof label")
    excerpt: str = Field(default="", description="Short source-backed excerpt or summary")
    confidence: float = Field(default=0.0, ge=0, le=1)


class IdentitySignal(BaseModel):
    """One signal used to decide whether a profile belongs to the candidate."""

    label: str = Field(description="Signal name")
    status: str = Field(description="match, weak_match, missing, or conflict")
    detail: str = Field(default="", description="Signal explanation")
    weight: float = Field(default=0.0, ge=0, le=1)


class IdentityMatch(BaseModel):
    """Overall identity confidence across profile evidence."""

    score: float = Field(default=0.0, ge=0, le=1)
    level: str = Field(default="unknown", description="high, medium, low, or unknown")
    signals: list[IdentitySignal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScoreComponent(BaseModel):
    """Transparent component used to explain social scoring."""

    name: str = Field(description="Component label")
    score: float = Field(default=0.0, ge=0)
    max_score: float = Field(default=0.0, gt=0)
    detail: str = Field(default="")


class SocialScoreBreakdown(BaseModel):
    """Transparent social scoring breakdown."""

    components: list[ScoreComponent] = Field(default_factory=list)
    total: float = Field(default=0.0, ge=0, le=100)
    confidence: float = Field(default=0.0, ge=0, le=1)


class ProviderStatus(BaseModel):
    """Configuration and run status for an external evidence provider."""

    provider: str = Field(description="Provider name")
    configured: bool = Field(default=False)
    enabled: bool = Field(default=True)
    status: str = Field(default="unknown", description="ready, missing_key, disabled, used, skipped, or error")
    detail: str = Field(default="")


class AuditEvent(BaseModel):
    """Timeline event for a social analysis run."""

    stage: str = Field(description="Pipeline stage")
    status: str = Field(description="started, success, skipped, warning, or error")
    message: str = Field(description="Human-readable event message")
    provider: str = Field(default="")
    url: str = Field(default="")


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
    evidence_profiles: list[ProfileEvidence] = Field(
        default_factory=list,
        description="Public profile evidence collected from resume and discovered links",
    )
    source_citations: list[EvidenceCitation] = Field(default_factory=list)
    identity_match: IdentityMatch = Field(default_factory=IdentityMatch)
    score_breakdown: SocialScoreBreakdown = Field(default_factory=SocialScoreBreakdown)
    provider_statuses: list[ProviderStatus] = Field(default_factory=list)
    audit_events: list[AuditEvent] = Field(default_factory=list)
    privacy_notes: list[str] = Field(default_factory=list)
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
    candidate_name: str = Field(default="", description="Candidate name for optional web discovery")
    github_username: str = Field(default="", description="GitHub username")
    linkedin_url: Optional[str] = Field(default=None, description="LinkedIn profile URL")
    twitter_handle: Optional[str] = Field(default=None, description="Twitter/X handle")
    profile_urls: list[str] = Field(
        default_factory=list,
        description="Public profile URLs extracted from the resume or supplied by the user",
    )
    approved_profile_urls: list[str] = Field(
        default_factory=list,
        description="Profile URLs explicitly approved by a reviewer",
    )
    rejected_profile_urls: list[str] = Field(
        default_factory=list,
        description="Profile URLs explicitly rejected by a reviewer",
    )
    web_discovery_enabled: bool = Field(default=True, description="Allow Brave Search profile discovery")
    firecrawl_enabled: bool = Field(default=True, description="Allow Firecrawl public page extraction")
    consent_confirmed: bool = Field(default=True, description="Reviewer confirms public-data screening is allowed")
    claimed_skills: list[str] = Field(
        default_factory=list, description="Skills from resume for verification"
    )

    @field_validator("github_username")
    @classmethod
    def validate_github_username(cls, v: str) -> str:
        """Strip @ prefix if present."""
        return v.lstrip("@")

    @model_validator(mode="after")
    def validate_profile_source(self) -> "SocialAnalyzeRequest":
        """Require at least one public profile source for social analysis."""
        if (
            self.github_username
            or self.linkedin_url
            or self.twitter_handle
            or self.profile_urls
            or self.approved_profile_urls
            or self.candidate_name
        ):
            return self
        raise ValueError("At least one public profile URL, handle, or candidate name is required")


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
