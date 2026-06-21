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
    GitHubProfile,
    GitHubRepo,
    LinkedInProfile,
    SocialAnalyzeRequest,
    SocialScoreResponse,
    TechVerification,
    TwitterProfile,
)

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

    Uses GitHub REST API (public, no auth needed). Rate limit: 60/hr.
    """
    username = state.request.github_username
    logger.info("Fetching GitHub profile for @%s", username)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # User profile
            user_resp = await client.get(
                f"https://api.github.com/users/{username}",
                headers={"Accept": "application/vnd.github.v3+json"},
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
                headers={"Accept": "application/vnd.github.v3+json"},
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
                location=user_data.get("location"),
                created_at=user_data.get("created_at"),
                repos=repos,
                languages=languages,
            )

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

    # Build prompt for LLM
    prompt = f"""You are an expert technical recruiter analyzing a candidate's social media presence.

{context}

Analyze this GitHub profile and provide a JSON response with this exact structure:
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

    state.social_score = round(min(100.0, score), 2)

    # Build basic tech verification
    if state.request.claimed_skills and gh.languages:
        claimed_lower = [s.lower() for s in state.request.claimed_skills]
        langs_lower = [l.lower() for l in gh.languages.keys()]
        verified = [s for s in claimed_lower if any(s in l or l in s for l in langs_lower)]
        unverified = [s for s in claimed_lower if s not in verified]
        state.tech_verification = TechVerification(
            verified=verified,
            unverified=unverified,
            discrepancies=[],
            confidence=0.5 if verified else 0.2,
        )

    state.findings = {
        "technical_depth": f"Has {gh.public_repos} public repos across {len(gh.languages)} languages",
        "contribution_quality": f"Total {total_stars} stars across repos",
        "thought_leadership": "Assessment requires LLM (fallback mode)",
        "community_engagement": f"{gh.followers} followers on GitHub",
        "activity_consistency": "Assessment requires LLM (fallback mode)",
    }

    return state


# ---------------------------------------------------------------------------
# LangGraph workflow builder
# ---------------------------------------------------------------------------

async def run_social_analysis(request: SocialAnalyzeRequest) -> SocialScoreResponse:
    """Run the complete social media intelligence workflow.

    Executes the LangGraph-style pipeline:
    1. GitHub fetch
    2. LinkedIn fetch (optional)
    3. Twitter fetch (optional)
    4. LLM synthesis

    Args:
        request: SocialAnalyzeRequest with candidate details.

    Returns:
        SocialScoreResponse with score and findings.
    """
    import time
    start = time.time()

    state = AgentState(request=request)

    # Run the pipeline sequentially (nodes depend on previous state)
    state = await fetch_github(state)
    state = await fetch_linkedin(state)
    state = await fetch_twitter(state)
    state = await synthesize(state)

    elapsed_ms = int((time.time() - start) * 1000)
    state.processing_time_ms = elapsed_ms

    logger.info(
        "Social analysis complete for %s: score=%.1f, time=%dms",
        request.github_username, state.social_score, elapsed_ms,
    )

    return SocialScoreResponse(
        social_score=state.social_score,
        github=state.github,
        linkedin=state.linkedin,
        twitter=state.twitter,
        findings=state.findings,
        tech_verification=state.tech_verification,
        red_flags=state.red_flags,
        warnings=state.warnings,
        processing_time_ms=elapsed_ms,
        cached=False,
    )
