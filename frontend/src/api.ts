import type {
  CandidateEvaluateResponse,
  HealthStatus,
  ResumeScoreResponse,
  SocialScoreResponse
} from "./types";

export interface ApiConfig {
  baseUrl: string;
  apiKey: string;
}

interface ScoreResumeInput {
  jobDescription: string;
  file: File;
  githubUsername?: string;
  signal?: AbortSignal;
}

interface AnalyzeSocialInput {
  candidateEmail: string;
  githubUsername: string;
  linkedinUrl?: string;
  twitterHandle?: string;
  claimedSkills: string[];
  signal?: AbortSignal;
}

interface EvaluateCandidateInput {
  resumeScore: number;
  socialScore: number;
  candidateName: string;
  candidateEmail: string;
  jobTitle: string;
  signal?: AbortSignal;
}

export class ApiError extends Error {
  status: number;
  details?: unknown;

  constructor(message: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

export class HireSignalApi {
  private readonly baseUrl: string;
  private readonly apiKey: string;

  constructor(config: ApiConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, "");
    this.apiKey = config.apiKey;
  }

  async health(signal?: AbortSignal): Promise<HealthStatus> {
    return this.requestJson<HealthStatus>("/health", { signal }, false);
  }

  async scoreResume(input: ScoreResumeInput): Promise<ResumeScoreResponse> {
    const formData = new FormData();
    formData.append("job_description", input.jobDescription);
    formData.append("resume_file", input.file);
    if (input.githubUsername?.trim()) {
      formData.append("github_username", input.githubUsername.trim().replace(/^@/, ""));
    }

    return this.requestJson<ResumeScoreResponse>("/api/v1/resume/score", {
      method: "POST",
      body: formData,
      signal: input.signal
    });
  }

  async analyzeSocial(input: AnalyzeSocialInput): Promise<SocialScoreResponse> {
    return this.requestJson<SocialScoreResponse>("/api/v1/social/analyze", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        candidate_email: input.candidateEmail,
        github_username: input.githubUsername.trim().replace(/^@/, ""),
        linkedin_url: input.linkedinUrl?.trim() || null,
        twitter_handle: input.twitterHandle?.trim() || null,
        claimed_skills: input.claimedSkills
      }),
      signal: input.signal
    });
  }

  async evaluateCandidate(input: EvaluateCandidateInput): Promise<CandidateEvaluateResponse> {
    return this.requestJson<CandidateEvaluateResponse>("/api/v1/candidate/evaluate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        resume_score: input.resumeScore,
        social_score: input.socialScore,
        candidate_name: input.candidateName,
        candidate_email: input.candidateEmail,
        job_title: input.jobTitle
      }),
      signal: input.signal
    });
  }

  private async requestJson<T>(
    path: string,
    init: RequestInit = {},
    authenticated = true
  ): Promise<T> {
    const headers = new Headers(init.headers);
    if (authenticated) {
      headers.set("X-API-Key", this.apiKey);
    }

    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers
    });

    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message =
        typeof payload === "object" && payload !== null
          ? String((payload as { message?: unknown; detail?: unknown; error?: unknown }).message ??
              (payload as { detail?: unknown }).detail ??
              (payload as { error?: unknown }).error ??
              `Request failed with ${response.status}`)
          : String(payload || `Request failed with ${response.status}`);

      throw new ApiError(message, response.status, payload);
    }

    return payload as T;
  }
}
