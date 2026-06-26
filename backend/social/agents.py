"""LangGraph-powered social media intelligence agents.

Implements a multi-node agent workflow:
  1. Fetch GitHub repos, stars, languages, contribution graph
  2. Fetch LinkedIn profile (if API key provided)
  3. Fetch Twitter/X posts (if API key provided)
  4. Synthesis LLM analyzes everything
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from backend.core.config import get_settings
from backend.core.llm_provider import api_base_url, api_headers, api_key
from backend.core.exceptions import LLMError, SocialMediaError
from backend.models.schemas import (
    AuditEvent,
    EvidenceCitation,
    GitHubProfile,
    GitHubRepo,
    IdentityMatch,
    IdentitySignal,
    LinkedInProfile,
    ProfileEvidence,
    ProviderStatus,
    ScoreComponent,
    SocialAnalyzeRequest,
    SocialScoreBreakdown,
    SocialScoreResponse,
    TechVerification,
    TwitterProfile,
)
from backend.social.evidence import collect_profile_evidence, extract_profile_urls, platform_from_url, username_from_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State for LangGraph workflow
# ---------------------------------------------------------------------------

@dataclass
class AgentState:
    """State object passed between LangGraph nodes."""

    request: SocialAnalyzeRequest
    github: GitHubProfile = field(default_factory=lambda: GitHubProfile(username=""))
    linkedin: LinkedInProfile = field(default_factory=lambda: LinkedInProfile(retrieved=False))
    twitter: TwitterProfile = field(default_factory=lambda: TwitterProfile(retrieved=False))
    profile_evidence: list[ProfileEvidence] = field(default_factory=list)
    discovered_urls: list[str] = field(default_factory=list)
    findings: dict[str, Any] = field(default_factory=dict)
    tech_verification: TechVerification = field(default_factory=lambda: TechVerification())
    red_flags: list[str] = field(default_factory=list)
    social_score: float = 0.0
    warnings: list[str] = field(default_factory=list)
    processing_time_ms: int = 0


# ---------------------------------------------------------------------------
# Node 1: GitHub Fetcher
# ---------------------------------------------------------------------------

async def fetch_github(state: AgentState) -> AgentState:
    """Fetch GitHub profile, repos, languages for the given username.

    Uses GitHub REST API. Public requests work without auth, but a token raises
    rate limits and makes repeated batch screening more reliable.
    """
    settings = get_settings()
    username = state.request.github_username
    if not username:
        for url in state.request.profile_urls:
            if platform_from_url(url) == "github":
                username = username_from_url(url, "github") or ""
                state.request.github_username = username
                break
    if not username:
        state.warnings.append("No GitHub username provided; relying on discovered profile URLs")
        return state

    logger.info("Fetching GitHub profile for @%s", username)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            github_headers = {"Accept": "application/vnd.github.v3+json"}
            if settings.GITHUB_TOKEN:
                github_headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"

            # User profile
            user_resp = await client.get(
                f"https://api.github.com/users/{username}",
                headers=github_headers,
            )

            if user_resp.status_code == 404:
                state.warnings.append(f"GitHub user @{username} not found")
                state.github = GitHubProfile(username=username)
                return state
            if user_resp.status_code == 403:
                state.warnings.append("GitHub API rate limit exceeded (60/hr without auth)")
                state.github = GitHubProfile(username=username)
                return state

            user_resp.raise_for_status()
            user_data = user_resp.json()

            # Repositories
            repos_resp = await client.get(
                f"https://api.github.com/users/{username}/repos",
                headers=github_headers,
                params={"sort": "updated", "per_page": 30},
            )
            repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

            repos: list[GitHubRepo] = []
            languages: dict[str, int] = {}

            for r in repos_data:
                repo = GitHubRepo(
                    name=r.get("name", ""),
                    language=r.get("language") or "Unknown",
                    stars=r.get("stargazers_count", 0),
                    forks=r.get("forks_count", 0),
                    description=r.get("description"),
                    is_fork=r.get("fork", False),
                    updated_at=r.get("updated_at"),
                )
                repos.append(repo)
                if repo.language and repo.language != "Unknown":
                    languages[repo.language] = languages.get(repo.language, 0) + 1

            state.github = GitHubProfile(
                username=username,
                public_repos=user_data.get("public_repos", 0),
                followers=user_data.get("followers", 0),
                following=user_data.get("following", 0),
                bio=user_data.get("bio"),
                company=user_data.get("company"),
                blog=user_data.get("blog"),
                twitter_username=user_data.get("twitter_username"),
                location=user_data.get("location"),
                created_at=user_data.get("created_at"),
                repos=repos,
                languages=languages,
            )

            state.discovered_urls.extend(extract_profile_urls(user_data.get("bio") or ""))
            if user_data.get("blog"):
                state.discovered_urls.append(user_data["blog"])
            if user_data.get("twitter_username"):
                state.discovered_urls.append(f"https://x.com/{user_data['twitter_username']}")

            try:
                readme_headers = {**github_headers, "Accept": "application/vnd.github.raw"}
                readme_resp = await client.get(
                    f"https://api.github.com/repos/{username}/{username}/readme",
                    headers=readme_headers,
                )
                if readme_resp.status_code == 200:
                    state.discovered_urls.extend(extract_profile_urls(getattr(readme_resp, "text", "")))
            except Exception as exc:
                state.warnings.append(f"GitHub profile README link discovery skipped: {exc}")

            logger.info(
                "GitHub: @%s has %d repos, %d followers, languages: %s",
                username, len(repos), state.github.followers,
                list(languages.keys()),
            )

    except Exception as exc:
        logger.error("GitHub fetch failed: %s", exc)
        state.warnings.append(f"GitHub fetch failed: {exc}")
        state.github = GitHubProfile(username=username)

    return state


# ---------------------------------------------------------------------------
# Node 2: LinkedIn Fetcher
# ---------------------------------------------------------------------------

async def fetch_linkedin(state: AgentState) -> AgentState:
    """Fetch LinkedIn profile if API key is configured.

    If no API key, skip gracefully with a warning.
    """
    settings = get_settings()
    if not settings.LINKEDIN_API_KEY:
        state.warnings.append("LinkedIn API key not configured; skipping LinkedIn analysis")
        return state

    if not state.request.linkedin_url:
        state.warnings.append("No LinkedIn URL provided; skipping LinkedIn analysis")
        return state

    logger.info("Fetching LinkedIn profile: %s", state.request.linkedin_url)

    try:
        # Note: LinkedIn's official API requires OAuth and special permissions.
        # This is a placeholder for a proper LinkedIn API integration.
        # In production, you'd use LinkedIn's API v2 or a service like Proxycurl.
        state.linkedin = LinkedInProfile(
            headline="LinkedIn profile retrieved (placeholder)",
            skills=[],
            retrieved=True,
        )
        state.warnings.append(
            "LinkedIn data is placeholder - full integration requires "
            "LinkedIn Marketing API or third-party service"
        )
    except Exception as exc:
        logger.error("LinkedIn fetch failed: %s", exc)
        state.warnings.append(f"LinkedIn fetch failed: {exc}")

    return state


# ---------------------------------------------------------------------------
# Node 3: Twitter Fetcher
# ---------------------------------------------------------------------------

async def fetch_twitter(state: AgentState) -> AgentState:
    """Fetch Twitter/X profile if API key is configured.

    If no API key, skip gracefully with a warning.
    """
    settings = get_settings()
    if not settings.TWITTER_BEARER_TOKEN:
        state.warnings.append("Twitter Bearer Token not configured; skipping Twitter analysis")
        return state

    handle = state.request.twitter_handle
    if not handle:
        state.warnings.append("No Twitter handle provided; skipping Twitter analysis")
        return state

    handle = handle.lstrip("@")
    logger.info("Fetching Twitter profile for @%s", handle)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get user by username
            user_resp = await client.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                headers={"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"},
                params={"user.fields": "description,public_metrics,created_at"},
            )

            if user_resp.status_code == 404:
                state.warnings.append(f"Twitter user @{handle} not found")
                return state
            if user_resp.status_code == 401:
                state.warnings.append("Twitter API credentials invalid")
                return state
            if user_resp.status_code == 429:
                state.warnings.append("Twitter API rate limit exceeded")
                return state

            user_resp.raise_for_status()
            user_data = user_resp.json().get("data", {})

            metrics = user_data.get("public_metrics", {})

            # Get recent tweets
            tweets_resp = await client.get(
                f"https://api.twitter.com/2/users/{user_data['id']}/tweets",
                headers={"Authorization": f"Bearer {settings.TWITTER_BEARER_TOKEN}"},
                params={"max_results": 10, "tweet.fields": "created_at"},
            )
            tweets_data = tweets_resp.json().get("data", []) if tweets_resp.status_code == 200 else []
            recent_tweets = [t.get("text", "") for t in tweets_data]

            state.twitter = TwitterProfile(
                description=user_data.get("description"),
                followers_count=metrics.get("followers_count", 0),
                tweet_count=metrics.get("tweet_count", 0),
                recent_tweets=recent_tweets,
                retrieved=True,
            )

            logger.info(
                "Twitter: @%s has %d followers, %d tweets",
                handle, state.twitter.followers_count, state.twitter.tweet_count,
            )

    except Exception as exc:
        logger.error("Twitter fetch failed: %s", exc)
        state.warnings.append(f"Twitter fetch failed: {exc}")

    return state


# ---------------------------------------------------------------------------
# Node 4: Synthesis LLM
# ---------------------------------------------------------------------------

async def synthesize(state: AgentState) -> AgentState:
    """Use LLM to synthesize social media findings into a score and insights.

    Analyzes:
    - Tech stack verification vs resume claims
    - Open source contribution quality
    - Thought leadership
    - Red flags
    - Overall social_score (0-100)
    """
    settings = get_settings()
    claimed_skills = state.request.claimed_skills

    # Build context for LLM
    github = state.github
    evidence_context = _format_profile_evidence(state.profile_evidence)
    context = f"""
# GitHub Analysis for @{github.username}

## Profile
- Public repos: {github.public_repos}
- Followers: {github.followers}
- Bio: {github.bio or "N/A"}
- Company: {github.company or "N/A"}
- Location: {github.location or "N/A"}
- Account created: {github.created_at or "N/A"}

## Languages Used
{json.dumps(github.languages, indent=2)}

## Top Repositories
    """
    for repo in github.repos[:10]:
        context += f"- {repo.name} ({repo.language}, {repo.stars} stars, {repo.forks} forks)\n"
        if repo.description:
            context += f"  {repo.description}\n"

    if claimed_skills:
        context += f"\n## Skills Claimed on Resume\n{', '.join(claimed_skills)}\n"
    if evidence_context:
        context += f"\n## Additional Public Profile Evidence\n{evidence_context}\n"

    # Build prompt for LLM
    prompt = f"""You are an expert technical recruiter analyzing a candidate's social media presence.

{context}

Analyze this GitHub profile and all additional public profile evidence. Prefer concrete public evidence over claims, treat Brave Search entries as discovery hints only, avoid over-crediting inaccessible profiles, and provide a JSON response with this exact structure:
{{
  "social_score": <number 0-100>,
  "findings": {{
    "technical_depth": "<assessment of technical skills based on repos, languages, code quality indicators>",
    "contribution_quality": "<assessment of open source contributions>",
    "thought_leadership": "<assessment of thought leadership via READMEs, project documentation, blog>",
    "community_engagement": "<assessment based on followers, stars, forks>",
    "activity_consistency": "<assessment of recent activity and consistency>"
  }},
  "tech_verification": {{
    "verified": ["<list of resume skills confirmed by GitHub repos/languages>"],
    "unverified": ["<list of resume skills NOT found on GitHub>"],
    "discrepancies": ["<any mismatches between claims and evidence>"],
    "confidence": <number 0.0-1.0>
  }},
  "red_flags": ["<list any concerns or red flags, empty array if none>"]
}}

Scoring guidelines for social_score:
- 80-100: Exceptional - active contributor, diverse projects, strong community presence, skills verified
- 60-79: Good - solid GitHub presence, some notable projects, most skills verified
- 40-59: Average - minimal GitHub activity, few repos, some skill verification
- 20-39: Below average - very little activity, hard to verify claims
- 0-19: Poor - no meaningful GitHub presence, cannot verify technical claims

Respond ONLY with valid JSON."""

    try:
        if not api_key(settings):
            # Fallback: compute score heuristically
            logger.warning("No AI provider API key; using heuristic social scoring")
            state = _heuristic_social_score(state)
            return state

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{api_base_url(settings)}/chat/completions",
                headers=api_headers(settings),
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a technical recruiting analysis engine. Respond only with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500,
                },
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Parse JSON response
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            llm_result = json.loads(content)

            state.social_score = float(llm_result.get("social_score", 50))
            state.findings = llm_result.get("findings", {})

            tv = llm_result.get("tech_verification", {})
            state.tech_verification = TechVerification(
                verified=tv.get("verified", []),
                unverified=tv.get("unverified", []),
                discrepancies=tv.get("discrepancies", []),
                confidence=float(tv.get("confidence", 0.5)),
            )
            state.red_flags = llm_result.get("red_flags", [])

            logger.info(
                "LLM synthesis complete: social_score=%.1f, verified=%d skills, flags=%d",
                state.social_score,
                len(state.tech_verification.verified),
                len(state.red_flags),
            )

    except json.JSONDecodeError as exc:
        logger.error("LLM returned invalid JSON: %s\nRaw: %s", exc, content[:500])
        state.warnings.append("LLM returned invalid JSON; using heuristic fallback")
        state = _heuristic_social_score(state)
    except LLMError:
        state.warnings.append("LLM call failed; using heuristic fallback")
        state = _heuristic_social_score(state)
    except Exception as exc:
        logger.error("Synthesis LLM failed: %s", exc)
        state.warnings.append(f"Synthesis failed: {exc}")
        state = _heuristic_social_score(state)

    return state


def _format_profile_evidence(evidence: list[ProfileEvidence]) -> str:
    """Format public profile evidence for the LLM prompt."""
    lines: list[str] = []
    for item in evidence[:12]:
        status = "retrieved" if item.retrieved else "not retrieved"
        lines.append(f"- {item.platform}: {item.url} ({status})")
        if item.username:
            lines.append(f"  username: {item.username}")
        if item.summary:
            lines.append(f"  summary: {item.summary[:500]}")
        if item.metrics:
            lines.append(f"  metrics: {json.dumps(item.metrics, default=str)[:800]}")
        if item.skills:
            lines.append(f"  inferred skills: {', '.join(item.skills[:20])}")
        if item.warnings:
            lines.append(f"  warnings: {'; '.join(item.warnings[:3])}")
    return "\n".join(lines)


def _heuristic_social_score(state: AgentState) -> AgentState:
    """Compute a heuristic social score when LLM is unavailable.

    Factors:
    - Number of repos (0-25)
    - Stars/forks as quality indicators (0-20)
    - Language diversity matching claimed skills (0-25)
    - Account age/activity (0-15)
    - Followers/community (0-15)
    """
    gh = state.github
    score = 0.0

    # Repos (0-25)
    score += min(25.0, gh.public_repos * 2.5)

    # Stars (0-20)
    total_stars = sum(r.stars for r in gh.repos)
    score += min(20.0, total_stars * 0.5)

    # Language diversity vs claimed skills (0-25)
    if state.request.claimed_skills and gh.languages:
        claimed_lower = set(s.lower() for s in state.request.claimed_skills)
        langs_lower = set(l.lower() for l in gh.languages.keys())
        matches = claimed_lower.intersection(langs_lower)
        if claimed_lower:
            score += min(25.0, (len(matches) / len(claimed_lower)) * 25.0)
    else:
        score += min(25.0, len(gh.languages) * 5.0)

    # Account age (0-15)
    if gh.created_at:
        try:
            from datetime import datetime
            created = datetime.fromisoformat(gh.created_at.replace("Z", "+00:00"))
            age_years = (datetime.now().replace(tzinfo=created.tzinfo) - created).days / 365
            score += min(15.0, age_years * 3.0)
        except Exception:
            score += 5.0
    else:
        score += 5.0

    # Followers (0-15)
    score += min(15.0, gh.followers * 0.3)

    # Additional public profile evidence (0-20)
    retrieved_evidence = [
        item for item in state.profile_evidence
        if item.retrieved and item.platform not in {"github", "brave_search"}
    ]
    evidence_skills = _evidence_skill_set(state.profile_evidence)
    score += min(20.0, len(retrieved_evidence) * 4.0 + len(evidence_skills) * 1.5)

    state.social_score = round(min(100.0, score), 2)

    # Build basic tech verification
    if state.request.claimed_skills and (gh.languages or evidence_skills):
        claimed_lower = [s.lower() for s in state.request.claimed_skills]
        langs_lower = [l.lower() for l in gh.languages.keys()]
        evidence_lower = [s.lower() for s in evidence_skills]
        verified = [
            s for s in claimed_lower
            if any(s in l or l in s for l in langs_lower)
            or any(s in e or e in s for e in evidence_lower)
        ]
        unverified = [s for s in claimed_lower if s not in verified]
        state.tech_verification = TechVerification(
            verified=verified,
            unverified=unverified,
            discrepancies=[],
            confidence=min(0.85, 0.35 + (len(verified) / max(1, len(claimed_lower))) * 0.5),
        )

    state.findings = {
        "technical_depth": f"Has {gh.public_repos} public repos across {len(gh.languages)} languages",
        "contribution_quality": f"Total {total_stars} stars across repos",
        "thought_leadership": f"{len(retrieved_evidence)} additional public profiles retrieved",
        "community_engagement": f"{gh.followers} followers on GitHub",
        "activity_consistency": "Assessment requires LLM (fallback mode)",
        "credential_evidence": [item.model_dump() for item in state.profile_evidence],
    }

    return state


def _evidence_skill_set(evidence: list[ProfileEvidence]) -> set[str]:
    """Collect skills inferred from public profile evidence."""
    skills: set[str] = set()
    for item in evidence:
        skills.update(skill.lower() for skill in item.skills)
    return skills


# ---------------------------------------------------------------------------
# LangGraph workflow builder
# ---------------------------------------------------------------------------

async def run_social_analysis(request: SocialAnalyzeRequest) -> SocialScoreResponse:
    """Run the complete social media intelligence workflow.

    Executes the LangGraph-style pipeline:
    1. GitHub fetch and profile-link discovery
    2. LinkedIn fetch (optional)
    3. Twitter fetch (optional)
    4. Additional public profile evidence collection
    5. LLM synthesis

    Args:
        request: SocialAnalyzeRequest with candidate details.

    Returns:
        SocialScoreResponse with score and findings.
    """
    import time
    start = time.time()

    state = AgentState(request=request)
    state.warnings.extend(_request_policy_warnings(request))

    # Run the pipeline sequentially (nodes depend on previous state)
    if request.consent_confirmed:
        state = await fetch_github(state)
        state = await fetch_linkedin(state)
        state = await fetch_twitter(state)
        evidence, evidence_warnings = await collect_profile_evidence(
            state.request,
            state.github,
            state.twitter,
            state.discovered_urls,
        )
        state.profile_evidence = evidence
        state.warnings.extend(evidence_warnings)
    else:
        state.warnings.append("Public profile screening skipped because consent was not confirmed")
    state = await synthesize(state)

    elapsed_ms = int((time.time() - start) * 1000)
    state.processing_time_ms = elapsed_ms
    identity_match = build_identity_match(request, state.github, state.profile_evidence)
    score_breakdown = build_score_breakdown(state, identity_match)
    source_citations = build_source_citations(state.profile_evidence)
    provider_statuses = build_provider_statuses(request, state.profile_evidence, state.warnings)
    audit_events = build_audit_events(state, provider_statuses)
    privacy_notes = build_privacy_notes(request)

    logger.info(
        "Social analysis complete for %s: score=%.1f, time=%dms",
        request.github_username, state.social_score, elapsed_ms,
    )

    return SocialScoreResponse(
        social_score=state.social_score,
        github=state.github,
        linkedin=state.linkedin,
        twitter=state.twitter,
        evidence_profiles=state.profile_evidence,
        source_citations=source_citations,
        identity_match=identity_match,
        score_breakdown=score_breakdown,
        provider_statuses=provider_statuses,
        audit_events=audit_events,
        privacy_notes=privacy_notes,
        findings=state.findings,
        tech_verification=state.tech_verification,
        red_flags=state.red_flags,
        warnings=state.warnings,
        processing_time_ms=elapsed_ms,
        cached=False,
    )


def build_source_citations(evidence: list[ProfileEvidence]) -> list[EvidenceCitation]:
    """Build source citations from evidence items."""
    citations: list[EvidenceCitation] = []
    for item in evidence:
        if item.platform == "brave_search":
            for link in item.links[:8]:
                citations.append(EvidenceCitation(
                    platform=item.platform,
                    url=link,
                    label="Discovered profile candidate",
                    excerpt="Found by Brave Search; requires reviewer confidence before heavy scoring.",
                    confidence=item.confidence,
                ))
            continue
        if not item.url:
            continue
        label = f"{item.platform} {'retrieved' if item.retrieved else 'not retrieved'}"
        excerpt = item.citation or item.summary or "; ".join(item.warnings[:2])
        citations.append(EvidenceCitation(
            platform=item.platform,
            url=item.url,
            label=label,
            excerpt=excerpt[:300],
            confidence=item.confidence,
        ))
    return citations[:24]


def build_identity_match(
    request: SocialAnalyzeRequest,
    github: GitHubProfile,
    evidence: list[ProfileEvidence],
) -> IdentityMatch:
    """Estimate whether collected profiles likely belong to the candidate."""
    signals: list[IdentitySignal] = []
    candidate_name = request.candidate_name.strip().lower()
    email_local = ""
    if request.candidate_email and "@local.hiresignal" not in request.candidate_email and "@" in request.candidate_email:
        email_local = request.candidate_email.split("@", 1)[0].replace(".", "").replace("_", "").lower()

    usernames = [item.username.lower() for item in evidence if item.username]
    if request.github_username:
        requested = request.github_username.lower()
        matched = any(username == requested for username in usernames) or github.username.lower() == requested
        signals.append(IdentitySignal(
            label="GitHub handle",
            status="match" if matched else "missing",
            detail=f"Requested @{request.github_username}; GitHub API returned @{github.username or 'none'}",
            weight=0.28 if matched else 0.0,
        ))

    if candidate_name:
        name_tokens = [token for token in candidate_name.replace("-", " ").split() if len(token) > 2]
        name_hits = 0
        for item in evidence:
            text = " ".join([item.summary, item.citation, item.username or ""]).lower()
            if name_tokens and any(token in text for token in name_tokens):
                name_hits += 1
        signals.append(IdentitySignal(
            label="Name similarity",
            status="match" if name_hits >= 2 else "weak_match" if name_hits == 1 else "missing",
            detail=f"{name_hits} evidence source(s) mention part of the candidate name",
            weight=min(0.24, name_hits * 0.12),
        ))

    if email_local:
        email_hits = sum(1 for username in usernames if email_local and (email_local in username.replace("-", "").replace("_", "") or username.replace("-", "").replace("_", "") in email_local))
        signals.append(IdentitySignal(
            label="Email/username overlap",
            status="match" if email_hits else "missing",
            detail=f"{email_hits} username(s) overlap with the email local part",
            weight=0.18 if email_hits else 0.0,
        ))

    cross_links = sum(len(item.links) for item in evidence if item.retrieved and item.platform != "brave_search")
    signals.append(IdentitySignal(
        label="Cross-linked profiles",
        status="match" if cross_links >= 2 else "weak_match" if cross_links == 1 else "missing",
        detail=f"{cross_links} public cross-link(s) discovered across profiles",
        weight=min(0.18, cross_links * 0.09),
    ))

    retrieved_count = sum(1 for item in evidence if item.retrieved and item.platform != "brave_search")
    signals.append(IdentitySignal(
        label="Verified public sources",
        status="match" if retrieved_count >= 2 else "weak_match" if retrieved_count == 1 else "missing",
        detail=f"{retrieved_count} non-search public source(s) retrieved",
        weight=min(0.12, retrieved_count * 0.06),
    ))

    score = round(min(1.0, sum(signal.weight for signal in signals)), 2)
    if score >= 0.72:
        level = "high"
    elif score >= 0.42:
        level = "medium"
    elif score > 0:
        level = "low"
    else:
        level = "unknown"

    warnings = []
    if any(item.platform == "brave_search" for item in evidence):
        warnings.append("Search-discovered profiles should be manually reviewed before relying on them")
    if level in {"low", "unknown"} and evidence:
        warnings.append("Identity confidence is limited; review profile ownership before final decisions")

    return IdentityMatch(score=score, level=level, signals=signals, warnings=warnings)


def build_score_breakdown(state: AgentState, identity_match: IdentityMatch) -> SocialScoreBreakdown:
    """Build a readable social scoring breakdown."""
    gh = state.github
    total_stars = sum(repo.stars for repo in gh.repos)
    retrieved_evidence = [
        item for item in state.profile_evidence
        if item.retrieved and item.platform not in {"github", "brave_search"}
    ]
    evidence_skills = _evidence_skill_set(state.profile_evidence)
    verified_count = len(state.tech_verification.verified)
    claimed_count = max(1, len(state.request.claimed_skills))

    components = [
        ScoreComponent(
            name="GitHub footprint",
            score=round(min(25.0, gh.public_repos * 2.5), 2),
            max_score=25,
            detail=f"{gh.public_repos} public repos",
        ),
        ScoreComponent(
            name="Project quality",
            score=round(min(20.0, total_stars * 0.5), 2),
            max_score=20,
            detail=f"{total_stars} sampled repo stars",
        ),
        ScoreComponent(
            name="Skill verification",
            score=round(min(25.0, (verified_count / claimed_count) * 25.0), 2),
            max_score=25,
            detail=f"{verified_count}/{len(state.request.claimed_skills)} claimed skills verified",
        ),
        ScoreComponent(
            name="Additional public evidence",
            score=round(min(20.0, len(retrieved_evidence) * 4.0 + len(evidence_skills) * 1.5), 2),
            max_score=20,
            detail=f"{len(retrieved_evidence)} extra profile(s), {len(evidence_skills)} inferred skill(s)",
        ),
        ScoreComponent(
            name="Identity confidence",
            score=round(identity_match.score * 10.0, 2),
            max_score=10,
            detail=f"{identity_match.level} confidence",
        ),
    ]
    component_total = round(sum(component.score for component in components), 2)
    confidence = round(min(1.0, (state.tech_verification.confidence * 0.55) + (identity_match.score * 0.45)), 2)
    return SocialScoreBreakdown(components=components, total=component_total, confidence=confidence)


def get_provider_statuses(request: SocialAnalyzeRequest | None = None) -> list[ProviderStatus]:
    """Return provider configuration and capability status."""
    settings = get_settings()
    request = request or SocialAnalyzeRequest(candidate_email="status@local.hiresignal", candidate_name="Status Check")
    return [
        ProviderStatus(
            provider="GitHub",
            configured=bool(settings.GITHUB_TOKEN),
            enabled=True,
            status="ready" if settings.GITHUB_TOKEN else "ready",
            detail="Uses GitHub public REST API; token raises rate limits" if settings.GITHUB_TOKEN else "Public API works without token but has lower rate limits",
        ),
        ProviderStatus(
            provider="Hugging Face",
            configured=bool(settings.HUGGINGFACE_TOKEN),
            enabled=True,
            status="ready" if settings.HUGGINGFACE_TOKEN else "ready",
            detail="Uses Hugging Face public API; token helps with allowed gated/private resources",
        ),
        ProviderStatus(
            provider="Brave Search",
            configured=bool(settings.BRAVE_SEARCH_API_KEY),
            enabled=settings.WEB_DISCOVERY_ENABLED and request.web_discovery_enabled,
            status="ready" if settings.BRAVE_SEARCH_API_KEY and settings.WEB_DISCOVERY_ENABLED and request.web_discovery_enabled else "missing_key" if not settings.BRAVE_SEARCH_API_KEY else "disabled",
            detail="Discovers missing profile URLs from public search",
        ),
        ProviderStatus(
            provider="Firecrawl",
            configured=bool(settings.FIRECRAWL_API_KEY),
            enabled=settings.FIRECRAWL_ENABLED and request.firecrawl_enabled,
            status="ready" if settings.FIRECRAWL_API_KEY and settings.FIRECRAWL_ENABLED and request.firecrawl_enabled else "missing_key" if not settings.FIRECRAWL_API_KEY else "disabled",
            detail="Extracts public pages without bypassing login/CAPTCHA",
        ),
        ProviderStatus(
            provider="LinkedIn",
            configured=bool(settings.LINKEDIN_API_KEY),
            enabled=bool(request.linkedin_url),
            status="ready" if settings.LINKEDIN_API_KEY and request.linkedin_url else "missing_key" if request.linkedin_url and not settings.LINKEDIN_API_KEY else "skipped",
            detail="Requires approved LinkedIn or trusted enrichment API access",
        ),
        ProviderStatus(
            provider="X/Twitter",
            configured=bool(settings.TWITTER_BEARER_TOKEN),
            enabled=bool(request.twitter_handle),
            status="ready" if settings.TWITTER_BEARER_TOKEN and request.twitter_handle else "missing_key" if request.twitter_handle and not settings.TWITTER_BEARER_TOKEN else "skipped",
            detail="Requires X API bearer token; public page scraping is disabled",
        ),
    ]


def build_provider_statuses(
    request: SocialAnalyzeRequest,
    evidence: list[ProfileEvidence],
    warnings: list[str],
) -> list[ProviderStatus]:
    """Annotate provider statuses with run usage."""
    statuses = get_provider_statuses(request)
    used_platforms = {item.platform for item in evidence if item.retrieved}
    used_sources = {item.source_type for item in evidence if item.retrieved}
    for item in statuses:
        provider_key = item.provider.lower().replace(" ", "_")
        if item.provider == "GitHub" and "github" in used_platforms:
            item.status = "used"
        elif item.provider == "Hugging Face" and "huggingface" in used_platforms:
            item.status = "used"
        elif item.provider == "Brave Search" and "brave_search" in used_platforms:
            item.status = "used"
        elif item.provider == "Firecrawl" and "firecrawl" in used_sources:
            item.status = "used"
        elif item.provider == "LinkedIn" and any(source.platform == "linkedin" for source in evidence):
            item.status = "skipped" if not item.configured else item.status
        elif item.provider == "X/Twitter" and any(source.platform == "twitter" for source in evidence):
            item.status = "skipped" if not item.configured else item.status
        if any(provider_key.split("_")[0] in warning.lower() for warning in warnings):
            if item.status not in {"used", "ready"}:
                item.detail = f"{item.detail}; see warnings"
    return statuses


def build_audit_events(state: AgentState, provider_statuses: list[ProviderStatus]) -> list[AuditEvent]:
    """Build a human-readable social-analysis timeline."""
    events = [
        AuditEvent(stage="policy", status="success" if state.request.consent_confirmed else "skipped", message="Public-data screening consent confirmed" if state.request.consent_confirmed else "Public-data screening disabled"),
        AuditEvent(stage="resume_links", status="success" if state.request.profile_urls else "skipped", message=f"{len(state.request.profile_urls)} profile URL(s) supplied from resume/user input"),
    ]
    for provider in provider_statuses:
        events.append(AuditEvent(
            stage="provider",
            provider=provider.provider,
            status="success" if provider.status == "used" else "warning" if provider.status == "missing_key" else "skipped" if provider.status in {"skipped", "disabled"} else "success",
            message=f"{provider.provider}: {provider.status}. {provider.detail}",
        ))
    for item in state.profile_evidence[:20]:
        events.append(AuditEvent(
            stage="evidence",
            provider=item.platform,
            status="success" if item.retrieved else "warning",
            message=item.citation or item.summary or "; ".join(item.warnings[:2]),
            url=item.url,
        ))
    for warning in state.warnings[:20]:
        events.append(AuditEvent(stage="warning", status="warning", message=warning))
    return events[:60]


def build_privacy_notes(request: SocialAnalyzeRequest) -> list[str]:
    """Return privacy and compliance notes for the run."""
    notes = [
        "Only public URLs and official/approved APIs are used for external evidence.",
        "LinkedIn and X/Twitter pages are not scraped behind login, CAPTCHA, or paywalls.",
        "Search-discovered profiles should be manually reviewed before final hiring decisions.",
        "Candidate data should be deleted when it is no longer needed for the hiring workflow.",
    ]
    if not request.consent_confirmed:
        notes.insert(0, "Public profile screening was disabled because consent was not confirmed.")
    if request.rejected_profile_urls:
        notes.append(f"{len(request.rejected_profile_urls)} reviewer-rejected profile URL(s) were excluded.")
    return notes


def _request_policy_warnings(request: SocialAnalyzeRequest) -> list[str]:
    """Warnings driven by reviewer policy toggles."""
    warnings: list[str] = []
    if not request.consent_confirmed:
        warnings.append("Consent not confirmed; external social evidence collection is disabled")
    if not request.web_discovery_enabled:
        warnings.append("Brave Search web discovery disabled by reviewer")
    if not request.firecrawl_enabled:
        warnings.append("Firecrawl public-page extraction disabled by reviewer")
    return warnings
