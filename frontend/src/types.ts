export type CandidateTier = "Tier 1" | "Tier 2" | "Tier 3" | "Reject";

export type SessionStatus =
  | "queued"
  | "scoring_resume"
  | "analyzing_social"
  | "evaluating"
  | "completed"
  | "failed"
  | "cancelled";

export interface ResumeScoreBreakdown {
  skill_match: number;
  experience_depth: number;
  education_certs: number;
  format_completeness: number;
}

export interface ParsedResume {
  name: string;
  email: string;
  phone: string;
  skills: string[];
  raw_text: string;
  profile_urls: string[];
  sections_found: string[];
  parse_quality: string;
}

export interface ResumeScoreResponse {
  total_score: number;
  breakdown: ResumeScoreBreakdown;
  extracted_data: ParsedResume;
  tier: CandidateTier;
  processing_time_ms: number;
  cached: boolean;
  warnings: string[];
}

export interface GitHubRepo {
  name: string;
  language?: string | null;
  stars: number;
  forks: number;
  description?: string | null;
  is_fork: boolean;
  updated_at?: string | null;
}

export interface GitHubProfile {
  username: string;
  public_repos: number;
  followers: number;
  following: number;
  bio?: string | null;
  company?: string | null;
  blog?: string | null;
  location?: string | null;
  created_at?: string | null;
  repos: GitHubRepo[];
  languages: Record<string, number>;
}

export interface TechVerification {
  verified: string[];
  unverified: string[];
  discrepancies: string[];
  confidence: number;
}

export interface ProfileEvidence {
  platform: string;
  url: string;
  username?: string | null;
  retrieved: boolean;
  summary: string;
  metrics: Record<string, unknown>;
  skills: string[];
  links: string[];
  warnings: string[];
  confidence: number;
  source_type: string;
  citation: string;
}

export interface EvidenceCitation {
  platform: string;
  url: string;
  label: string;
  excerpt: string;
  confidence: number;
}

export interface IdentitySignal {
  label: string;
  status: string;
  detail: string;
  weight: number;
}

export interface IdentityMatch {
  score: number;
  level: string;
  signals: IdentitySignal[];
  warnings: string[];
}

export interface ScoreComponent {
  name: string;
  score: number;
  max_score: number;
  detail: string;
}

export interface SocialScoreBreakdown {
  components: ScoreComponent[];
  total: number;
  confidence: number;
}

export interface ProviderStatus {
  provider: string;
  configured: boolean;
  enabled: boolean;
  status: string;
  detail: string;
}

export interface AuditEvent {
  stage: string;
  status: string;
  message: string;
  provider: string;
  url: string;
}

export interface SocialScoreResponse {
  social_score: number;
  github: GitHubProfile;
  linkedin: { retrieved: boolean; [key: string]: unknown };
  twitter: { retrieved: boolean; [key: string]: unknown };
  evidence_profiles: ProfileEvidence[];
  source_citations: EvidenceCitation[];
  identity_match: IdentityMatch;
  score_breakdown: SocialScoreBreakdown;
  provider_statuses: ProviderStatus[];
  audit_events: AuditEvent[];
  privacy_notes: string[];
  findings: Record<string, unknown>;
  tech_verification: TechVerification;
  red_flags: string[];
  warnings: string[];
  processing_time_ms: number;
  cached: boolean;
}

export interface TierAssignment {
  tier: CandidateTier;
  label: string;
  recommendation: string;
  confidence: number;
}

export interface FinalReport {
  candidate_name: string;
  candidate_email: string;
  job_title: string;
  resume_score: number;
  social_score: number;
  weighted_total: number;
  tier: TierAssignment;
  conclusion: string;
  strengths: string[];
  concerns: string[];
  next_steps: string;
  processed_at: string;
}

export interface CandidateEvaluateResponse {
  report: FinalReport;
  processing_time_ms: number;
  cached: boolean;
}

export interface HealthStatus {
  status: string;
  version: string;
  services: Record<string, string>;
  timestamp: string;
}

export interface CandidateSession {
  id: string;
  file: File;
  githubUsername: string;
  linkedinUrl: string;
  twitterHandle: string;
  approvedProfileUrls: string[];
  rejectedProfileUrls: string[];
  webDiscoveryEnabled: boolean;
  firecrawlEnabled: boolean;
  consentConfirmed: boolean;
  emailOverride: string;
  nameOverride: string;
  status: SessionStatus;
  progress: number;
  activeStep: string;
  logs: string[];
  startedAt?: number;
  completedAt?: number;
  resume?: ResumeScoreResponse;
  social?: SocialScoreResponse;
  evaluation?: CandidateEvaluateResponse;
  error?: string;
}

export interface SerializableCandidate {
  id: string;
  fileName: string;
  githubUsername: string;
  linkedinUrl?: string;
  twitterHandle?: string;
  approvedProfileUrls?: string[];
  rejectedProfileUrls?: string[];
  status: SessionStatus;
  error?: string;
  resume?: ResumeScoreResponse;
  social?: SocialScoreResponse;
  evaluation?: CandidateEvaluateResponse;
}
