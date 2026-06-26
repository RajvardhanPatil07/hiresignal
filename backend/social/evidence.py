"""Public profile discovery and evidence collection for candidate scoring."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.core.config import get_settings
from backend.models.schemas import GitHubProfile, ProfileEvidence, SocialAnalyzeRequest, TwitterProfile


PROFILE_URL_PATTERN = re.compile(
    r"(?:(?:https?://)?(?:www\.)?"
    r"(?:github\.com|linkedin\.com|twitter\.com|x\.com|huggingface\.co|"
    r"kaggle\.com|leetcode\.com|hackerrank\.com|codechef\.com|codeforces\.com)"
    r"/[^\s<>\]\[()\"']+)",
    re.I,
)

KNOWN_SKILLS = {
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust", "ruby",
    "php", "swift", "kotlin", "scala", "react", "angular", "vue", "next.js",
    "django", "flask", "fastapi", "express", "node.js", "graphql", "sql",
    "postgresql", "mysql", "mongodb", "redis", "docker", "kubernetes", "aws",
    "azure", "gcp", "tensorflow", "pytorch", "pandas", "numpy", "scikit-learn",
    "spark", "hadoop", "kafka", "airflow", "terraform", "linux", "bash",
}

HTML_HEADERS = {
    "User-Agent": "HireSignal/1.0 (+https://localhost; public candidate profile verifier)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
FIRECRAWL_SCRAPE_URL = "https://api.firecrawl.dev/v2/scrape"
SUPPORTED_PROFILE_HOSTS = {
    "github.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "huggingface.co",
    "kaggle.com",
    "leetcode.com",
    "hackerrank.com",
    "codechef.com",
    "codeforces.com",
}
RESERVED_PROFILE_SLUGS = {
    "about", "api", "blog", "business", "collections", "company", "contest",
    "developers", "discuss", "enterprise", "events", "explore", "features",
    "jobs", "learn", "login", "marketplace", "news", "orgs", "pricing",
    "problemset", "problems", "search", "settings", "signup", "topics",
}


def normalize_url(url: str) -> str:
    """Normalize a candidate profile URL."""
    cleaned = url.strip().rstrip(".,;:)]}>\"'")
    if not cleaned:
        return ""
    if not re.match(r"^https?://", cleaned, re.I):
        cleaned = f"https://{cleaned}"
    return cleaned


def extract_profile_urls(text: str) -> list[str]:
    """Extract supported public profile URLs from arbitrary text."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in PROFILE_URL_PATTERN.finditer(text or ""):
        url = normalize_url(match.group(0))
        key = canonical_key(url)
        if key and key not in seen:
            seen.add(key)
            urls.append(url)
    return urls[:20]


def canonical_key(url: str) -> str:
    """Return a lowercase URL key for de-duplication."""
    if not url:
        return ""
    parsed = urlparse(normalize_url(url))
    return f"{parsed.netloc.lower().removeprefix('www.')}{parsed.path.rstrip('/').lower()}"


def platform_from_url(url: str) -> str:
    """Detect the supported platform for a URL."""
    host = urlparse(normalize_url(url)).netloc.lower().removeprefix("www.")
    if host == "github.com":
        return "github"
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin"
    if host in {"twitter.com", "x.com"}:
        return "twitter"
    if host == "huggingface.co":
        return "huggingface"
    if host == "kaggle.com":
        return "kaggle"
    if host == "leetcode.com":
        return "leetcode"
    if host == "hackerrank.com":
        return "hackerrank"
    if host == "codechef.com":
        return "codechef"
    if host == "codeforces.com":
        return "codeforces"
    return "portfolio"


def is_supported_profile_url(url: str) -> bool:
    """Return whether a URL belongs to a supported public profile host."""
    host = urlparse(normalize_url(url)).netloc.lower().removeprefix("www.")
    if host not in SUPPORTED_PROFILE_HOSTS:
        return False
    platform = platform_from_url(url)
    username = username_from_url(url, platform)
    if not username or username.lower() in RESERVED_PROFILE_SLUGS:
        return False
    if platform == "linkedin":
        parts = [p for p in urlparse(normalize_url(url)).path.split("/") if p]
        return len(parts) > 1 and parts[0] == "in"
    return True


def username_from_url(url: str, platform: str | None = None) -> str | None:
    """Extract a username-like slug from a supported profile URL."""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    parts = [p for p in parsed.path.split("/") if p]
    platform = platform or platform_from_url(normalized)
    if not parts:
        return None
    if platform == "linkedin" and parts[0] == "in" and len(parts) > 1:
        return parts[1]
    if platform == "leetcode" and parts[0] in {"u", "profile"} and len(parts) > 1:
        return parts[1]
    if platform in {"codechef", "codeforces"} and parts[0] in {"users", "profile"} and len(parts) > 1:
        return parts[1]
    if platform == "huggingface" and parts[0] in {"models", "datasets", "spaces"} and len(parts) > 1:
        return parts[1]
    return parts[0]


def profile_home_url(url: str) -> str:
    """Return the canonical profile homepage for a supported URL."""
    platform = platform_from_url(url)
    username = username_from_url(url, platform)
    if not username:
        return normalize_url(url)
    if platform == "github":
        return f"https://github.com/{username}"
    if platform == "linkedin":
        return f"https://www.linkedin.com/in/{username}"
    if platform == "twitter":
        return f"https://x.com/{username}"
    if platform == "huggingface":
        return f"https://huggingface.co/{username}"
    if platform == "kaggle":
        return f"https://www.kaggle.com/{username}"
    if platform == "leetcode":
        return f"https://leetcode.com/u/{username}"
    if platform == "hackerrank":
        return f"https://www.hackerrank.com/{username}"
    if platform == "codechef":
        return f"https://www.codechef.com/users/{username}"
    if platform == "codeforces":
        return f"https://codeforces.com/profile/{username}"
    return normalize_url(url)


def seed_profile_urls(
    request: SocialAnalyzeRequest,
    github: GitHubProfile,
    discovered_urls: list[str],
) -> list[str]:
    """Build the initial candidate-owned URL set from request and discovered public links."""
    seeds: list[str] = []
    if request.github_username:
        seeds.append(f"https://github.com/{request.github_username}")
    if request.linkedin_url:
        seeds.append(request.linkedin_url)
    if request.twitter_handle:
        seeds.append(f"https://x.com/{request.twitter_handle.lstrip('@')}")
    if github.blog:
        seeds.append(github.blog)
    if github.twitter_username:
        seeds.append(f"https://x.com/{github.twitter_username}")
    seeds.extend(request.profile_urls)
    seeds.extend(request.approved_profile_urls)
    seeds.extend(discovered_urls)

    normalized: list[str] = []
    seen: set[str] = set()
    for url in seeds:
        cleaned = normalize_url(url)
        key = canonical_key(cleaned)
        if key and key not in seen:
            seen.add(key)
            normalized.append(cleaned)
    return normalized[:15]


async def collect_profile_evidence(
    request: SocialAnalyzeRequest,
    github: GitHubProfile,
    twitter: TwitterProfile,
    discovered_urls: list[str],
) -> tuple[list[ProfileEvidence], list[str]]:
    """Collect public evidence from candidate-provided and discovered profile URLs."""
    warnings: list[str] = []
    evidence: list[ProfileEvidence] = []
    settings = get_settings()
    urls = seed_profile_urls(request, github, discovered_urls)
    rejected_keys = {canonical_key(url) for url in request.rejected_profile_urls}
    urls = [url for url in urls if canonical_key(url) not in rejected_keys]
    github_added = False

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        if request.web_discovery_enabled:
            brave_urls, brave_evidence, brave_warnings = await discover_profile_urls_with_brave(client, request, urls)
            warnings.extend(brave_warnings)
            if brave_evidence:
                evidence.append(brave_evidence)
            urls = merge_urls([*urls, *brave_urls])
            urls = [url for url in urls if canonical_key(url) not in rejected_keys]
        else:
            warnings.append("Web profile discovery disabled by request")

        firecrawl_budget = settings.FIRECRAWL_MAX_PAGES if settings.FIRECRAWL_ENABLED and request.firecrawl_enabled else 0
        for url in urls:
            platform = platform_from_url(url)
            if platform == "github":
                if not github_added:
                    evidence.append(github_to_evidence(github, url))
                    github_added = True
                continue
            if platform == "twitter":
                evidence.append(twitter_to_evidence(twitter, url))
                continue
            if platform == "linkedin":
                evidence.append(linkedin_placeholder(url))
                continue
            if platform == "huggingface":
                item = await fetch_huggingface(client, url)
            elif platform == "leetcode":
                item = await fetch_leetcode(client, url)
            elif platform == "codeforces":
                item = await fetch_codeforces(client, url)
            else:
                item = await fetch_public_profile(client, url, platform, use_firecrawl=firecrawl_budget > 0)
                if item.metrics.get("source") == "firecrawl":
                    firecrawl_budget -= 1
            evidence.append(item)
            warnings.extend(item.warnings)

    return evidence, warnings


def merge_urls(urls: list[str]) -> list[str]:
    """Normalize and dedupe URLs while preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for url in urls:
        cleaned = normalize_url(url)
        key = canonical_key(cleaned)
        if key and key not in seen:
            seen.add(key)
            merged.append(cleaned)
    return merged[:20]


def build_discovery_queries(request: SocialAnalyzeRequest, max_queries: int = 6) -> list[str]:
    """Build conservative Brave Search queries for missing candidate profiles."""
    name = clean_query_text(request.candidate_name)
    email = clean_query_text(request.candidate_email)
    email_local = ""
    if email and "@local.hiresignal" not in email and "@" in email:
        email_local = clean_query_text(email.split("@", 1)[0].replace(".", " ").replace("_", " "))

    usernames = {request.github_username.strip()} if request.github_username else set()
    for url in request.profile_urls:
        username = username_from_url(url)
        if username:
            usernames.add(username)

    queries: list[str] = []
    if name:
        quoted = f'"{name}"'
        queries.extend([
            f"{quoted} github linkedin kaggle leetcode huggingface",
            f'{quoted} "software engineer" github',
            f'{quoted} site:linkedin.com/in',
            f'{quoted} site:huggingface.co OR site:kaggle.com',
            f'{quoted} site:leetcode.com OR site:codeforces.com OR site:codechef.com OR site:hackerrank.com',
        ])
    if email and "@local.hiresignal" not in email:
        queries.append(f'"{email}"')
    if email_local:
        queries.append(f'"{email_local}" github linkedin')
    for username in sorted(usernames):
        cleaned = clean_query_text(username)
        if cleaned:
            queries.append(f'"{cleaned}" linkedin kaggle leetcode huggingface codeforces')

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            deduped.append(query)
    return deduped[:max(1, max_queries)]


async def discover_profile_urls_with_brave(
    client: httpx.AsyncClient,
    request: SocialAnalyzeRequest,
    existing_urls: list[str],
) -> tuple[list[str], ProfileEvidence | None, list[str]]:
    """Use Brave Search to discover likely public candidate profile URLs."""
    settings = get_settings()
    warnings: list[str] = []
    if not settings.WEB_DISCOVERY_ENABLED:
        return [], None, warnings
    if not settings.BRAVE_SEARCH_API_KEY:
        warnings.append("Brave Search API key not configured; web profile discovery skipped")
        return [], None, warnings

    queries = build_discovery_queries(request, settings.WEB_DISCOVERY_MAX_QUERIES)
    if not queries:
        return [], None, warnings

    discovered: list[str] = []
    existing_keys = {canonical_key(url) for url in existing_urls}
    seen = set(existing_keys)
    result_count = max(1, min(10, settings.WEB_DISCOVERY_MAX_RESULTS))
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": settings.BRAVE_SEARCH_API_KEY,
    }

    for query in queries:
        try:
            response = await client.get(
                BRAVE_SEARCH_URL,
                headers=headers,
                params={"q": query, "count": result_count, "safesearch": "strict"},
            )
            if response.status_code in {401, 403}:
                warnings.append("Brave Search credentials rejected; web discovery skipped")
                break
            if response.status_code == 429:
                warnings.append("Brave Search rate limit exceeded; web discovery stopped")
                break
            response.raise_for_status()
            payload = response.json()
            results = (payload.get("web") or {}).get("results") or []
            for result in results:
                candidates = extract_profile_urls(" ".join([
                    str(result.get("url") or ""),
                    str(result.get("title") or ""),
                    str(result.get("description") or ""),
                ]))
                for url in candidates:
                    if not is_supported_profile_url(url):
                        continue
                    canonical = profile_home_url(url)
                    key = canonical_key(canonical)
                    if key and key not in seen:
                        seen.add(key)
                        discovered.append(canonical)
        except Exception as exc:
            warnings.append(f"Brave Search discovery failed for query '{query[:60]}': {exc}")

    if not discovered:
        return [], None, warnings

    evidence = ProfileEvidence(
        platform="brave_search",
        url=BRAVE_SEARCH_URL,
        username=None,
        retrieved=True,
        summary=f"Discovered {len(discovered)} candidate profile URL(s) from public web search.",
        metrics={"queries": len(queries), "new_profile_urls": len(discovered), "source": "brave_search"},
        links=discovered[:10],
        warnings=warnings.copy(),
        confidence=0.45,
        source_type="search",
        citation=f"Brave Search returned {len(discovered)} supported profile URL(s).",
    )
    return discovered[:10], evidence, warnings


def clean_query_text(text: str | None) -> str:
    """Keep search query text compact and safe."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:120]


def github_to_evidence(github: GitHubProfile, url: str) -> ProfileEvidence:
    """Represent already-fetched GitHub data as generic evidence."""
    total_stars = sum(repo.stars for repo in github.repos)
    repo_names = ", ".join(repo.name for repo in github.repos[:5])
    summary = (
        f"{github.public_repos} public repos, {github.followers} followers, "
        f"{total_stars} stars across sampled repos. Top repos: {repo_names or 'none'}."
    )
    return ProfileEvidence(
        platform="github",
        url=url,
        username=github.username,
        retrieved=bool(github.username),
        summary=summary,
        metrics={
            "public_repos": github.public_repos,
            "followers": github.followers,
            "following": github.following,
            "sampled_repo_stars": total_stars,
            "languages": github.languages,
        },
        skills=sorted(github.languages.keys()),
        links=[link for link in [github.blog, f"https://x.com/{github.twitter_username}" if github.twitter_username else None] if link],
        confidence=0.9 if github.username else 0.0,
        source_type="public_api",
        citation=summary,
    )


def twitter_to_evidence(twitter: TwitterProfile, url: str) -> ProfileEvidence:
    """Represent Twitter/X API data as generic evidence."""
    if not twitter.retrieved:
        return ProfileEvidence(
            platform="twitter",
            url=url,
            username=username_from_url(url, "twitter"),
            retrieved=False,
            warnings=["Twitter/X profile requires TWITTER_BEARER_TOKEN; public page scraping is disabled"],
            confidence=0.2,
            source_type="skipped",
            citation="Twitter/X data was not retrieved because API credentials are required.",
        )
    text = " ".join([twitter.description or "", *twitter.recent_tweets[:5]])
    return ProfileEvidence(
        platform="twitter",
        url=url,
        username=username_from_url(url, "twitter"),
        retrieved=True,
        summary=twitter.description or "Twitter/X profile retrieved",
        metrics={"followers_count": twitter.followers_count, "tweet_count": twitter.tweet_count},
        skills=infer_skills(text),
        confidence=0.75,
        source_type="public_api",
        citation=twitter.description or "Twitter/X public metrics retrieved through API",
    )


def linkedin_placeholder(url: str) -> ProfileEvidence:
    """LinkedIn should be collected through official/approved API access."""
    return ProfileEvidence(
        platform="linkedin",
        url=url,
        username=username_from_url(url, "linkedin"),
        retrieved=False,
        warnings=["LinkedIn URL discovered, but LinkedIn scraping is disabled; configure approved LinkedIn/Proxycurl-style API access"],
        confidence=0.2,
        source_type="skipped",
        citation="LinkedIn URL was found but not scraped.",
    )


async def fetch_huggingface(client: httpx.AsyncClient, url: str) -> ProfileEvidence:
    """Fetch Hugging Face public user, model, and dataset signals."""
    settings = get_settings()
    username = username_from_url(url, "huggingface")
    if not username:
        return failed_evidence("huggingface", url, "Could not detect Hugging Face username")
    warnings: list[str] = []
    skills: set[str] = set()
    metrics: dict[str, Any] = {}
    summary_parts: list[str] = []
    headers = {"Authorization": f"Bearer {settings.HUGGINGFACE_TOKEN}"} if settings.HUGGINGFACE_TOKEN else {}

    try:
        user_resp = await client.get(f"https://huggingface.co/api/users/{username}", headers=headers)
        if user_resp.status_code == 404:
            return failed_evidence("huggingface", url, f"Hugging Face user {username} not found")
        if user_resp.status_code < 400:
            user_data = user_resp.json()
            metrics["followers"] = user_data.get("numFollowers") or user_data.get("followers")
            summary_parts.append(user_data.get("fullname") or username)
    except Exception as exc:
        warnings.append(f"Hugging Face user fetch failed: {exc}")

    try:
        models_resp = await client.get(
            "https://huggingface.co/api/models",
            params={"author": username, "limit": 20},
            headers=headers,
        )
        models = models_resp.json() if models_resp.status_code == 200 else []
        metrics["models"] = len(models)
        metrics["model_likes"] = sum(int(model.get("likes") or 0) for model in models if isinstance(model, dict))
        for model in models:
            if not isinstance(model, dict):
                continue
            for tag in model.get("tags") or []:
                skills.update(infer_skills(str(tag)))
            skills.update(infer_skills(" ".join(str(model.get(k) or "") for k in ("modelId", "pipeline_tag", "library_name"))))
    except Exception as exc:
        warnings.append(f"Hugging Face model fetch failed: {exc}")

    try:
        datasets_resp = await client.get(
            "https://huggingface.co/api/datasets",
            params={"author": username, "limit": 20},
            headers=headers,
        )
        datasets = datasets_resp.json() if datasets_resp.status_code == 200 else []
        metrics["datasets"] = len(datasets)
    except Exception as exc:
        warnings.append(f"Hugging Face dataset fetch failed: {exc}")

    summary_parts.append(f"{metrics.get('models', 0)} models and {metrics.get('datasets', 0)} datasets")
    return ProfileEvidence(
        platform="huggingface",
        url=url,
        username=username,
        retrieved=True,
        summary=", ".join(part for part in summary_parts if part),
        metrics=metrics,
        skills=sorted(skills),
        warnings=warnings,
        confidence=0.75 if not warnings else 0.55,
        source_type="public_api",
        citation=", ".join(part for part in summary_parts if part),
    )


async def fetch_leetcode(client: httpx.AsyncClient, url: str) -> ProfileEvidence:
    """Fetch public LeetCode profile signals through its public GraphQL endpoint."""
    username = username_from_url(url, "leetcode")
    if not username:
        return failed_evidence("leetcode", url, "Could not detect LeetCode username")

    query = """
    query userPublicProfile($username: String!) {
      matchedUser(username: $username) {
        username
        profile { realName aboutMe ranking reputation }
        submitStats { acSubmissionNum { difficulty count } }
      }
      userContestRanking(username: $username) {
        attendedContestsCount
        rating
        globalRanking
      }
    }
    """
    try:
        response = await client.post(
            "https://leetcode.com/graphql",
            json={"query": query, "variables": {"username": username}},
            headers={"Referer": "https://leetcode.com", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json().get("data", {})
        user = data.get("matchedUser")
        if not user:
            return failed_evidence("leetcode", url, f"LeetCode user {username} not found")
        profile = user.get("profile") or {}
        ac_counts = {
            item.get("difficulty", "Unknown"): item.get("count", 0)
            for item in ((user.get("submitStats") or {}).get("acSubmissionNum") or [])
        }
        contest = data.get("userContestRanking") or {}
        metrics = {
            "ranking": profile.get("ranking"),
            "reputation": profile.get("reputation"),
            "accepted_total": ac_counts.get("All", 0),
            "accepted_easy": ac_counts.get("Easy", 0),
            "accepted_medium": ac_counts.get("Medium", 0),
            "accepted_hard": ac_counts.get("Hard", 0),
            "contest_rating": contest.get("rating"),
            "contests": contest.get("attendedContestsCount"),
            "global_ranking": contest.get("globalRanking"),
        }
        return ProfileEvidence(
            platform="leetcode",
            url=url,
            username=username,
            retrieved=True,
            summary=f"{metrics['accepted_total']} accepted problems, ranking {metrics['ranking']}",
            metrics=metrics,
            skills=["algorithms", "data structures"],
            confidence=0.7,
            source_type="public_api",
            citation=f"LeetCode reports {metrics['accepted_total']} accepted problems.",
        )
    except Exception as exc:
        return failed_evidence("leetcode", url, f"LeetCode fetch failed: {exc}")


async def fetch_codeforces(client: httpx.AsyncClient, url: str) -> ProfileEvidence:
    """Fetch Codeforces public user and rating signals through the official API."""
    username = username_from_url(url, "codeforces")
    if not username:
        return failed_evidence("codeforces", url, "Could not detect Codeforces handle")

    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    summary_parts: list[str] = []

    try:
        info_resp = await client.get("https://codeforces.com/api/user.info", params={"handles": username})
        info_resp.raise_for_status()
        payload = info_resp.json()
        if payload.get("status") != "OK" or not payload.get("result"):
            return failed_evidence("codeforces", url, payload.get("comment") or f"Codeforces user {username} not found")
        info = payload["result"][0]
        metrics.update({
            "rating": info.get("rating"),
            "max_rating": info.get("maxRating"),
            "rank": info.get("rank"),
            "max_rank": info.get("maxRank"),
            "contribution": info.get("contribution"),
            "friend_of_count": info.get("friendOfCount"),
        })
        summary_parts.append(
            f"{info.get('rank', 'unrated')} rating {info.get('rating', 'n/a')} "
            f"(max {info.get('maxRating', 'n/a')})"
        )
    except Exception as exc:
        return failed_evidence("codeforces", url, f"Codeforces user fetch failed: {exc}")

    try:
        rating_resp = await client.get("https://codeforces.com/api/user.rating", params={"handle": username})
        if rating_resp.status_code == 200:
            rating_payload = rating_resp.json()
            contests = rating_payload.get("result") or []
            metrics["rated_contests"] = len(contests)
            if contests:
                best = min(contests, key=lambda item: item.get("rank", 10**9))
                latest = contests[-1]
                metrics["best_contest_rank"] = best.get("rank")
                metrics["latest_rating_update"] = latest.get("newRating")
        else:
            warnings.append(f"Codeforces rating fetch returned HTTP {rating_resp.status_code}")
    except Exception as exc:
        warnings.append(f"Codeforces rating fetch failed: {exc}")

    return ProfileEvidence(
        platform="codeforces",
        url=url,
        username=username,
        retrieved=True,
        summary=", ".join(summary_parts),
        metrics=metrics,
        skills=["algorithms", "data structures", "competitive programming"],
        warnings=warnings,
        confidence=0.8 if not warnings else 0.65,
        source_type="public_api",
        citation=", ".join(summary_parts),
    )


async def fetch_public_profile(
    client: httpx.AsyncClient,
    url: str,
    platform: str,
    use_firecrawl: bool = True,
) -> ProfileEvidence:
    """Fetch public metadata from a candidate-provided profile page."""
    firecrawl_warning: list[str] = []
    if use_firecrawl:
        firecrawl_item = await fetch_firecrawl_profile(client, url, platform)
        if firecrawl_item and firecrawl_item.retrieved:
            return firecrawl_item
        if firecrawl_item:
            firecrawl_warning = firecrawl_item.warnings

    try:
        response = await client.get(url, headers=HTML_HEADERS)
        if response.status_code in {401, 403}:
            return failed_evidence(platform, url, f"{platform} blocked public profile fetch with {response.status_code}")
        if response.status_code == 404:
            return failed_evidence(platform, url, f"{platform} profile not found")
        response.raise_for_status()
        html = response.text[:150_000]
        title = extract_tag_text(html, "title")
        description = extract_meta_description(html)
        text = strip_html(f"{title}\n{description}\n{html[:20_000]}")
        links = extract_profile_urls(html)
        metrics = extract_public_metrics(text)
        metrics["source"] = "direct_http"
        return ProfileEvidence(
            platform=platform,
            url=str(response.url),
            username=username_from_url(str(response.url), platform),
            retrieved=True,
            summary=(description or title or f"{platform} profile retrieved")[:500],
            metrics=metrics,
            skills=infer_skills(text),
            links=links[:10],
            warnings=firecrawl_warning,
            confidence=0.55,
            source_type="direct_http",
            citation=(description or title or f"{platform} profile retrieved")[:240],
        )
    except Exception as exc:
        return failed_evidence(platform, url, f"{platform} profile fetch failed: {exc}")


async def fetch_firecrawl_profile(
    client: httpx.AsyncClient,
    url: str,
    platform: str,
) -> ProfileEvidence | None:
    """Fetch a public profile page through Firecrawl and return clean evidence."""
    settings = get_settings()
    if not settings.FIRECRAWL_ENABLED or not settings.FIRECRAWL_API_KEY:
        return None
    if platform in {"linkedin", "twitter"}:
        return None

    try:
        response = await client.post(
            FIRECRAWL_SCRAPE_URL,
            headers={
                "Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["markdown", "links"],
                "onlyMainContent": True,
            },
        )
        if response.status_code in {401, 403}:
            return failed_evidence(platform, url, "Firecrawl credentials rejected; falling back to direct public fetch")
        if response.status_code == 429:
            return failed_evidence(platform, url, "Firecrawl rate limit exceeded; falling back to direct public fetch")
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        markdown = clean_text(data.get("markdown") or data.get("content") or "")
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        raw_links = data.get("links") if isinstance(data.get("links"), list) else []
        links = merge_urls([
            *(extract_profile_urls(markdown)),
            *(str(link) for link in raw_links if is_supported_profile_url(str(link))),
        ])
        summary = clean_text(
            str(metadata.get("description") or metadata.get("ogDescription") or metadata.get("title") or markdown[:500])
        )[:500]
        metrics = extract_public_metrics(markdown)
        metrics["source"] = "firecrawl"
        return ProfileEvidence(
            platform=platform,
            url=str(metadata.get("sourceURL") or metadata.get("url") or url),
            username=username_from_url(url, platform),
            retrieved=True,
            summary=summary or f"{platform} profile retrieved through Firecrawl",
            metrics=metrics,
            skills=infer_skills(markdown),
            links=links[:10],
            confidence=0.65,
            source_type="firecrawl",
            citation=summary or f"{platform} profile retrieved through Firecrawl",
        )
    except Exception as exc:
        return failed_evidence(platform, url, f"Firecrawl scrape failed; falling back to direct public fetch: {exc}")


def failed_evidence(platform: str, url: str, warning: str) -> ProfileEvidence:
    """Build a failed evidence item with a warning."""
    return ProfileEvidence(
        platform=platform,
        url=url,
        username=username_from_url(url, platform),
        retrieved=False,
        warnings=[warning],
        confidence=0.1,
        source_type="skipped" if "disabled" in warning.lower() or "requires" in warning.lower() else "error",
        citation=warning,
    )


def extract_tag_text(html: str, tag: str) -> str:
    """Extract a simple HTML tag body."""
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.I | re.S)
    return clean_text(match.group(1)) if match else ""


def extract_meta_description(html: str) -> str:
    """Extract a meta description or Open Graph description."""
    patterns = [
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if match:
            return clean_text(match.group(1))
    return ""


def strip_html(html: str) -> str:
    """Remove scripts, styles, and HTML tags from a small page sample."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(text)


def clean_text(text: str) -> str:
    """Normalize whitespace and entities."""
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def infer_skills(text: str) -> list[str]:
    """Infer known skills from text."""
    lowered = (text or "").lower()
    found = []
    for skill in sorted(KNOWN_SKILLS):
        if re.search(r"\b" + re.escape(skill) + r"\b", lowered):
            found.append(skill)
    return found[:30]


def extract_public_metrics(text: str) -> dict[str, Any]:
    """Extract common public coding-profile metrics from text."""
    metrics: dict[str, Any] = {}
    patterns = {
        "followers": r"([\d,]+)\s+followers",
        "stars": r"([\d,]+)\s+stars",
        "solved": r"([\d,]+)\s+(?:problems\s+)?solved",
        "rating": r"rating\s*[:\-]?\s*([\d,.]+)",
        "rank": r"rank(?:ing)?\s*[:\-]?\s*#?\s*([\d,]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            raw = match.group(1).replace(",", "")
            try:
                metrics[key] = float(raw) if "." in raw else int(raw)
            except ValueError:
                metrics[key] = match.group(1)
    return metrics
