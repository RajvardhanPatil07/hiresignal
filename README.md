# HireSignal - ATS with Social Media Intelligence

A complete Applicant Tracking System that combines resume parsing and scoring with social media intelligence to provide comprehensive, data-driven candidate evaluations.

## Architecture

```
hiresignal/
├── backend/
│   ├── api/           # FastAPI main application
│   ├── resume/        # Resume parsing & scoring engine
│   ├── social/        # Social media intelligence (LangGraph agents)
│   ├── synthesis/     # Final scoring & conclusion engine
│   ├── models/        # Pydantic v2 schemas
│   ├── core/          # Config, auth, cache, rate limiting
│   └── tests/         # pytest suite (80%+ coverage)
├── frontend/          # React dashboard for parallel candidate testing
├── docker-compose.yml
├── .env.example
└── README.md
```

## Modules

| Module | Description | Endpoint |
|--------|-------------|----------|
| **Resume Scoring** | Parse PDF/DOCX resumes, score against job descriptions | `POST /api/v1/resume/score` |
| **Social Intelligence** | Analyze GitHub, LinkedIn, Twitter via LangGraph agents | `POST /api/v1/social/analyze` |
| **Candidate Evaluation** | Combine scores into final weighted report | `POST /api/v1/candidate/evaluate` |
| **Frontend Dashboard** | Upload and evaluate multiple candidates in parallel | `http://127.0.0.1:5173` |

## Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose (optional, recommended)
- OpenAI or OpenRouter API key (optional; enables embeddings and LLM synthesis)

### Option 1: Docker Compose (Recommended)

```bash
# 1. Clone and navigate
cd hiresignal

# 2. Copy environment config
cp .env.example .env
# Edit .env and configure either OpenAI or OpenRouter

# 3. Start all services
docker-compose up --build

# 4. API is available at http://localhost:8000
# 5. Frontend dashboard at http://localhost:5173
# 6. API docs at http://localhost:8000/docs
# 7. Flower (Celery monitoring) at http://localhost:5555
```

### Option 2: Local Development

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 2. Install dependencies
cd backend
pip install -r requirements.txt

# 3. Set environment variables
cp ../.env.example ../.env
# Edit .env with your API keys

# 4. Start Redis (required for caching)
# macOS: brew install redis && redis-server
# Linux: sudo apt install redis-server && redis-server

# 5. Run the application
uvicorn backend.api.main:app --reload --port 8000

# 6. Start the frontend dashboard in a second terminal
cd ../frontend
npm install
npm run dev

# 7. Run backend tests
cd ../backend
pytest tests/ -v --tb=short
```

## Frontend Dashboard

The React dashboard lives in `frontend/` and gives you an end-to-end candidate testing UI:

- Batch upload PDF/DOCX resumes.
- Configure API URL, API key, job title, and job description.
- Add GitHub usernames manually or paste one username per line for a batch.
- Run multiple candidate pipelines in parallel with a configurable concurrency limit.
- Review per-candidate logs, warnings, scores, final tier, recommendations, and export CSV/JSON results.

Run it locally:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173` while the API is running on `http://127.0.0.1:8000`.

## API Documentation

Interactive API docs available at `http://localhost:8000/docs` (Swagger UI) or `http://localhost:8000/redoc` (ReDoc).

### Authentication

All API endpoints require the `X-API-Key` header:

```bash
X-API-Key: dev-api-key-change-in-production
```

### Rate Limiting

100 requests per minute per API key.

---

### 1. Score Resume

Parse and score a resume against a job description.

**Endpoint:** `POST /api/v1/resume/score`

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/resume/score \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -F "job_description=We are looking for a Senior Python Backend Engineer with 5+ years of experience in FastAPI, PostgreSQL, Docker, and Kubernetes. AWS certification preferred." \
  -F "resume_file=@/path/to/resume.pdf" \
  -F "github_username=janesmith"
```

**Response:**
```json
{
  "total_score": 78.5,
  "breakdown": {
    "skill_match": 32.0,
    "experience_depth": 24.5,
    "education_certs": 14.0,
    "format_completeness": 8.0
  },
  "extracted_data": {
    "name": "Jane Smith",
    "email": "jane.smith@example.com",
    "phone": "+1-555-123-4567",
    "skills": ["python", "fastapi", "docker", "kubernetes", "aws", "postgresql"],
    "experience": [...],
    "education": [...],
    "certifications": [...]
  },
  "tier": "Tier 2",
  "processing_time_ms": 2340,
  "cached": false,
  "warnings": []
}
```

---

### 2. Analyze Social Media

Fetch and analyze GitHub, LinkedIn, and Twitter profiles.

**Endpoint:** `POST /api/v1/social/analyze`

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/social/analyze \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -H "Content-Type: application/json" \
  -d '{
    "candidate_email": "jane.smith@example.com",
    "github_username": "janesmith",
    "linkedin_url": "https://linkedin.com/in/janesmith",
    "twitter_handle": "@janesmith",
    "claimed_skills": ["python", "fastapi", "docker", "kubernetes", "aws"]
  }'
```

**Response:**
```json
{
  "social_score": 72.0,
  "github": {
    "username": "janesmith",
    "public_repos": 25,
    "followers": 150,
    "bio": "Senior Backend Engineer | Python enthusiast",
    "repos": [...],
    "languages": {"Python": 15, "Go": 5, "TypeScript": 3}
  },
  "linkedin": {
    "retrieved": false
  },
  "twitter": {
    "retrieved": false
  },
  "findings": {
    "technical_depth": "Strong Python ecosystem expertise...",
    "contribution_quality": "Well-documented repos...",
    "thought_leadership": "Active blog contributor...",
    "community_engagement": "150 followers...",
    "activity_consistency": "Regular commits..."
  },
  "tech_verification": {
    "verified": ["python", "fastapi", "docker", "kubernetes"],
    "unverified": ["aws"],
    "discrepancies": [],
    "confidence": 0.82
  },
  "red_flags": [],
  "warnings": [
    "LinkedIn API key not configured; skipping LinkedIn analysis",
    "Twitter Bearer Token not configured; skipping Twitter analysis"
  ],
  "processing_time_ms": 4520,
  "cached": false
}
```

---

### 3. Evaluate Candidate

Combine resume and social scores into a final evaluation report.

**Endpoint:** `POST /api/v1/candidate/evaluate`

**Request:**
```bash
curl -X POST http://localhost:8000/api/v1/candidate/evaluate \
  -H "X-API-Key: dev-api-key-change-in-production" \
  -H "Content-Type: application/json" \
  -d '{
    "resume_score": 82.5,
    "social_score": 72.0,
    "candidate_name": "Jane Smith",
    "candidate_email": "jane.smith@example.com",
    "job_title": "Senior Python Backend Engineer"
  }'
```

**Response:**
```json
{
  "report": {
    "candidate_name": "Jane Smith",
    "candidate_email": "jane.smith@example.com",
    "job_title": "Senior Python Backend Engineer",
    "resume_score": 82.5,
    "social_score": 72.0,
    "weighted_total": 78.3,
    "tier": {
      "tier": "Tier 2",
      "label": "Strong Candidate",
      "recommendation": "Human review required before proceeding",
      "confidence": 0.80
    },
    "conclusion": "Jane Smith presents a strong profile for Senior Python Backend Engineer with a weighted score of 78.3/100. The resume demonstrates solid qualifications across all required skill areas, and the GitHub analysis confirms active development in Python and FastAPI...",
    "strengths": [
      "Strong resume with relevant skills and experience",
      "Excellent skill-to-job match",
      "GitHub profile supports technical claims",
      "Good overall alignment between stated and demonstrated capabilities"
    ],
    "concerns": [],
    "next_steps": "Assign to recruiter for human review. Schedule 15-min screening call. Prepare follow-up questions on experience gaps.",
    "processed_at": "2024-06-19T12:00:00+00:00"
  },
  "processing_time_ms": 850,
  "cached": false
}
```

---

### 4. Health Check

Check system health status.

**Endpoint:** `GET /health`

```bash
curl http://localhost:8000/health
```

---

## Scoring Breakdown

### Resume Score (0-100)

| Category | Max Points | Criteria |
|----------|-----------|----------|
| **Skill Match** | 40 | Exact keyword match (25) + Semantic similarity via embeddings (15) |
| **Experience Depth** | 30 | Years relevant (15) + Seniority (10) + Industry match (5) |
| **Education & Certs** | 20 | Degree relevance (10) + Certifications (10) |
| **Format & Completeness** | 10 | ATS-parseable (5) + Sections complete (5) |

### Social Score (0-100)

Determined by LLM analysis of GitHub/LinkedIn/Twitter data:
- Technical depth and language diversity
- Open source contribution quality (stars, forks, documentation)
- Thought leadership (blog posts, talks, README quality)
- Community engagement (followers, collaboration)
- Activity consistency over time
- Tech stack verification against resume claims
- Red flag detection

### Weighted Total = (Resume Score x 0.60) + (Social Score x 0.40)

### Tier Assignments

| Score | Tier | Action |
|-------|------|--------|
| 90-100 | **Tier 1** | Auto-advance to interview |
| 75-89 | **Tier 2** | Human review required |
| 60-74 | **Tier 3** | Conditional - gather more data |
| <60 | **Reject** | Auto-reject with feedback |

## LangGraph Agent Workflow

The social media intelligence module uses a sequential LangGraph workflow:

```
[Start] -> [GitHub Fetch] -> [LinkedIn Fetch] -> [Twitter Fetch] -> [LLM Synthesis] -> [End]
                |                    |                  |                  |
            Repos, Stars        Profile Data      Posts, Metrics      Score, Findings,
            Languages           (if API key)      (if API key)        Verification,
            Contributions                                             Red Flags
```

- LinkedIn and Twitter are **gracefully skipped** if API keys are not configured
- All LLM calls have **fallback heuristics** if the API fails
- **No raw social media content** is stored - only synthesized insights

## Development

### Running Tests

```bash
cd backend
pytest tests/ -v

# With coverage report
pytest tests/ -v --cov=backend --cov-report=term-missing --cov-fail-under=80
```

### Test Structure

| Test File | Coverage |
|-----------|----------|
| `test_resume.py` | Parser helpers, keyword matching, scoring logic, tier assignment |
| `test_social.py` | GitHub API mocking, LinkedIn/Twitter skip logic, heuristic fallback |
| `test_synthesis.py` | Weighted totals, tier boundaries, conclusion generation |
| `test_api.py` | End-to-end endpoint tests with mocked external APIs |

### Project Structure Details

```
backend/
├── api/
│   ├── main.py           # FastAPI app factory
│   ├── health.py         # Health check endpoints
│   └── middleware.py     # (reserved for future middleware)
├── resume/
│   ├── parser.py         # PDF/DOCX text extraction & structured parsing
│   ├── scorer.py         # Scoring engine with embeddings
│   └── routes.py         # FastAPI routes for resume endpoints
├── social/
│   ├── agents.py         # LangGraph workflow + GitHub/LinkedIn/Twitter fetchers
│   └── routes.py         # FastAPI routes for social endpoints
├── synthesis/
│   ├── engine.py         # Weighted scoring, tier assignment, conclusion generation
│   └── routes.py         # FastAPI routes for evaluation endpoints
├── models/
│   └── schemas.py        # All Pydantic v2 request/response models
├── core/
│   ├── config.py         # Settings management (pydantic-settings)
│   ├── auth.py           # API key authentication
│   ├── cache.py          # Redis cache utilities
│   ├── rate_limiter.py   # Sliding window rate limiting
│   ├── exceptions.py     # Custom exception hierarchy
│   └── logging_config.py # Structured logging setup
└── tests/
    ├── conftest.py       # Shared fixtures and test data
    ├── fixtures/         # Sample resume files
    ├── test_resume.py
    ├── test_social.py
    ├── test_synthesis.py
    └── test_api.py
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `openai` | AI provider: `openai` or `openrouter` |
| `LLM_MODEL` | No | `gpt-4o-mini` | Any model ID supported by the selected provider |
| `EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model ID supported by the selected provider |
| `OPENAI_API_KEY` | Conditional | - | Required when `LLM_PROVIDER=openai` |
| `OPENROUTER_API_KEY` | Conditional | - | Required when `LLM_PROVIDER=openrouter` |
| `OPENROUTER_BASE_URL` | No | `https://openrouter.ai/api/v1` | OpenRouter OpenAI-compatible API URL |
| `OPENROUTER_SITE_URL` | No | `http://localhost:8000` | Optional app URL sent to OpenRouter |
| `OPENROUTER_APP_NAME` | No | `HireSignal` | Optional app title sent to OpenRouter |
| `API_KEY` | Yes | `dev-api-key-change-in-production` | Internal API key for endpoint auth |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection string |
| `QDRANT_HOST` | No | `localhost` | Qdrant vector DB host |
| `LINKEDIN_API_KEY` | No | - | LinkedIn API key (optional) |
| `TWITTER_BEARER_TOKEN` | No | - | Twitter/X Bearer Token (optional) |
| `RESUME_WEIGHT` | No | `0.60` | Resume score weight (0-1) |
| `SOCIAL_WEIGHT` | No | `0.40` | Social score weight (0-1) |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | No | `100` | Rate limit per API key |

## Tech Stack

- **Python 3.12+** - Core language
- **FastAPI + Uvicorn** - Web framework
- **Pydantic v2** - Data validation
- **pdfplumber + python-docx** - Resume parsing
- **OpenAI-compatible AI APIs** - OpenAI or custom OpenRouter chat/embedding models
- **LangGraph** - Social media agent workflow
- **Redis** - Caching + rate limiting
- **Qdrant** - Vector database for skill embeddings
- **Celery + Flower** - Background tasks + monitoring
- **Docker + Docker Compose** - Containerization
- **pytest + httpx** - Testing

## License

MIT License - See LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please ensure tests pass (`pytest`) and code follows the existing style before submitting.
