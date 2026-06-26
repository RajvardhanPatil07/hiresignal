import type { CandidateSession, SerializableCandidate, SessionStatus } from "./types";

export const defaultJobDescription = `Senior Python Backend Engineer

We are looking for an engineer with strong Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, and distributed systems experience. The role requires clean API design, production debugging, test automation, and strong collaboration with product teams.`;

export function createCandidateSession(file: File): CandidateSession {
  return {
    id: crypto.randomUUID(),
    file,
    githubUsername: "",
    linkedinUrl: "",
    twitterHandle: "",
    approvedProfileUrls: [],
    rejectedProfileUrls: [],
    webDiscoveryEnabled: true,
    firecrawlEnabled: true,
    consentConfirmed: true,
    emailOverride: "",
    nameOverride: "",
    status: "queued",
    progress: 0,
    activeStep: "Queued",
    logs: [`Added ${file.name}`]
  };
}

export function githubUsernameFromUrls(urls: string[] = []): string {
  for (const url of urls) {
    try {
      const parsed = new URL(url.startsWith("http") ? url : `https://${url}`);
      const host = parsed.hostname.replace(/^www\./, "").toLowerCase();
      const [username] = parsed.pathname.split("/").filter(Boolean);
      if (host === "github.com" && username && !["orgs", "users", "topics"].includes(username)) {
        return username;
      }
    } catch {
      // Ignore malformed profile URLs from parsed resume text.
    }
  }
  return "";
}

export function guessGitHubFromFilename(fileName: string): string {
  return fileName
    .replace(/\.(pdf|docx)$/i, "")
    .replace(/resume|cv/gi, "")
    .replace(/[_\s]+/g, "-")
    .replace(/[^a-zA-Z0-9-]/g, "")
    .replace(/^-+|-+$/g, "")
    .toLowerCase();
}

export function statusLabel(status: SessionStatus): string {
  const labels: Record<SessionStatus, string> = {
    queued: "Queued",
    scoring_resume: "Scoring resume",
    analyzing_social: "Analyzing social",
    evaluating: "Building report",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled"
  };

  return labels[status];
}

export function scoreTone(score?: number): "high" | "medium" | "low" | "muted" {
  if (score === undefined || Number.isNaN(score)) return "muted";
  if (score >= 80) return "high";
  if (score >= 60) return "medium";
  return "low";
}

export function formatMs(ms?: number): string {
  if (ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function candidateRuntime(candidate: CandidateSession): string {
  if (!candidate.startedAt) return "—";
  const end = candidate.completedAt ?? Date.now();
  return formatMs(end - candidate.startedAt);
}

export function serializeCandidate(candidate: CandidateSession): SerializableCandidate {
  return {
    id: candidate.id,
    fileName: candidate.file.name,
    githubUsername: candidate.githubUsername,
    linkedinUrl: candidate.linkedinUrl || undefined,
    twitterHandle: candidate.twitterHandle || undefined,
    approvedProfileUrls: candidate.approvedProfileUrls,
    rejectedProfileUrls: candidate.rejectedProfileUrls,
    status: candidate.status,
    error: candidate.error,
    resume: candidate.resume,
    social: candidate.social,
    evaluation: candidate.evaluation
  };
}

export function downloadJson(fileName: string, value: unknown): void {
  downloadBlob(fileName, JSON.stringify(value, null, 2), "application/json");
}

export function downloadCsv(fileName: string, candidates: CandidateSession[]): void {
  const headers = [
    "file",
    "candidate_name",
    "candidate_email",
    "github",
    "status",
    "resume_score",
    "social_score",
    "weighted_total",
    "tier",
    "recommendation",
    "error"
  ];

  const rows = candidates.map((candidate) => {
    const report = candidate.evaluation?.report;
    const parsed = candidate.resume?.extracted_data;
    return [
      candidate.file.name,
      report?.candidate_name || candidate.nameOverride || parsed?.name || "",
      report?.candidate_email || candidate.emailOverride || parsed?.email || "",
      candidate.githubUsername,
      candidate.status,
      candidate.resume?.total_score ?? "",
      candidate.social?.social_score ?? "",
      report?.weighted_total ?? "",
      report?.tier.tier ?? "",
      report?.tier.recommendation ?? "",
      candidate.error ?? ""
    ].map(csvCell);
  });

  downloadBlob(fileName, [headers.map(csvCell), ...rows].map((row) => row.join(",")).join("\n"), "text/csv");
}

function csvCell(value: unknown): string {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

function downloadBlob(fileName: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
