import { type ChangeEvent, type DragEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, HireSignalApi } from "./api";
import type { CandidateSession, HealthStatus, ProviderStatus, SessionStatus } from "./types";
import {
  candidateRuntime,
  createCandidateSession,
  defaultJobDescription,
  downloadCsv,
  downloadJson,
  formatMs,
  githubUsernameFromUrls,
  scoreTone,
  serializeCandidate,
  statusLabel
} from "./utils";

type CandidatePatch = Partial<CandidateSession> | ((candidate: CandidateSession) => Partial<CandidateSession>);

const runningStatuses: SessionStatus[] = ["scoring_resume", "analyzing_social", "evaluating"];

function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState(
    () => localStorage.getItem("hiresignal.apiBaseUrl") ?? import.meta.env.VITE_HIRESIGNAL_API_BASE_URL ?? "http://127.0.0.1:8000"
  );
  const [apiKey, setApiKey] = useState(
    () => localStorage.getItem("hiresignal.apiKey") ?? import.meta.env.VITE_HIRESIGNAL_API_KEY ?? "dev-api-key-change-in-production"
  );
  const [jobTitle, setJobTitle] = useState(() => localStorage.getItem("hiresignal.jobTitle") ?? "Senior Python Backend Engineer");
  const [jobDescription, setJobDescription] = useState(
    () => localStorage.getItem("hiresignal.jobDescription") ?? defaultJobDescription
  );
  const [concurrency, setConcurrency] = useState(4);
  const [candidates, setCandidates] = useState<CandidateSession[]>([]);
  const [bulkHandles, setBulkHandles] = useState("");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [providerStatuses, setProviderStatuses] = useState<ProviderStatus[]>([]);
  const [healthError, setHealthError] = useState("");
  const [globalMessage, setGlobalMessage] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    localStorage.setItem("hiresignal.apiBaseUrl", apiBaseUrl);
  }, [apiBaseUrl]);

  useEffect(() => {
    localStorage.setItem("hiresignal.apiKey", apiKey);
  }, [apiKey]);

  useEffect(() => {
    localStorage.setItem("hiresignal.jobTitle", jobTitle);
  }, [jobTitle]);

  useEffect(() => {
    localStorage.setItem("hiresignal.jobDescription", jobDescription);
  }, [jobDescription]);

  const api = useMemo(() => new HireSignalApi({ baseUrl: apiBaseUrl, apiKey }), [apiBaseUrl, apiKey]);

  const updateCandidate = useCallback((id: string, patch: CandidatePatch) => {
    setCandidates((current) =>
      current.map((candidate) => {
        if (candidate.id !== id) return candidate;
        const nextPatch = typeof patch === "function" ? patch(candidate) : patch;
        return { ...candidate, ...nextPatch };
      })
    );
  }, []);

  const appendLog = useCallback(
    (id: string, message: string) => {
      updateCandidate(id, (candidate) => ({
        logs: [...candidate.logs, `${new Date().toLocaleTimeString()} · ${message}`]
      }));
    },
    [updateCandidate]
  );

  const checkHealth = useCallback(async () => {
    setHealthError("");
    try {
      const result = await api.health();
      setHealth(result);
      try {
        setProviderStatuses(await api.providerStatuses());
      } catch {
        setProviderStatuses([]);
      }
    } catch (error) {
      setHealth(null);
      setProviderStatuses([]);
      setHealthError(error instanceof Error ? error.message : "Could not reach backend");
    }
  }, [api]);

  useEffect(() => {
    void checkHealth();
  }, [checkHealth]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const incoming = Array.from(files);
    const valid = incoming.filter((file) => /\.(pdf|docx)$/i.test(file.name));
    const invalidCount = incoming.length - valid.length;

    if (valid.length > 0) {
      setCandidates((current) => [...current, ...valid.map(createCandidateSession)]);
      setGlobalMessage(`Added ${valid.length} candidate${valid.length === 1 ? "" : "s"}.`);
    }

    if (invalidCount > 0) {
      setGlobalMessage(`${invalidCount} file${invalidCount === 1 ? "" : "s"} skipped. Upload PDF or DOCX resumes only.`);
    }
  }, []);

  const handleFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    if (event.target.files) {
      addFiles(event.target.files);
      event.target.value = "";
    }
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setIsDragging(false);
    addFiles(event.dataTransfer.files);
  };

  const applyBulkHandles = () => {
    const handles = bulkHandles
      .split(/\r?\n/)
      .map((line) => line.trim().replace(/^@/, ""))
      .filter(Boolean);

    if (handles.length === 0) {
      setGlobalMessage("Paste one GitHub username per line first.");
      return;
    }

    setCandidates((current) =>
      current.map((candidate, index) => ({
        ...candidate,
        githubUsername: handles[index] ?? candidate.githubUsername
      }))
    );
    setGlobalMessage(`Applied ${Math.min(handles.length, candidates.length)} GitHub handle${handles.length === 1 ? "" : "s"}.`);
  };

  const removeCandidate = (id: string) => {
    setCandidates((current) => current.filter((candidate) => candidate.id !== id));
  };

  const clearFinished = () => {
    setCandidates((current) => current.filter((candidate) => !["completed", "failed", "cancelled"].includes(candidate.status)));
  };

  const resetCandidate = (id: string) => {
    updateCandidate(id, {
      status: "queued",
      progress: 0,
      activeStep: "Queued",
      error: undefined,
      startedAt: undefined,
      completedAt: undefined,
      resume: undefined,
      social: undefined,
      evaluation: undefined
    });
  };

  const runCandidate = useCallback(
    async (candidate: CandidateSession, signal: AbortSignal) => {
      const startedAt = Date.now();
      const providedGithubUsername = candidate.githubUsername.trim().replace(/^@/, "");

      updateCandidate(candidate.id, {
        status: "scoring_resume",
        progress: 10,
        activeStep: "Uploading and scoring resume",
        error: undefined,
        startedAt,
        completedAt: undefined,
        resume: undefined,
        social: undefined,
        evaluation: undefined
      });
      appendLog(candidate.id, "Started resume scoring");

      try {
        const resume = await api.scoreResume({
          jobDescription,
          file: candidate.file,
          githubUsername: providedGithubUsername,
          signal
        });
        const profileUrls = resume.extracted_data.profile_urls ?? [];
        const githubUsername = providedGithubUsername || githubUsernameFromUrls(profileUrls);

        updateCandidate(candidate.id, {
          resume,
          status: "analyzing_social",
          progress: 48,
          activeStep: "Analyzing GitHub and social signals"
        });
        appendLog(candidate.id, `Resume score ${resume.total_score.toFixed(1)} (${resume.tier})`);
        if (profileUrls.length > 0) {
          appendLog(candidate.id, `Discovered ${profileUrls.length} public profile link${profileUrls.length === 1 ? "" : "s"} in resume`);
        }

        const candidateEmail =
          candidate.emailOverride.trim() || resume.extracted_data.email || `candidate-${candidate.id.slice(0, 8)}@local.hiresignal`;
        const candidateName = candidate.nameOverride.trim() || resume.extracted_data.name || candidate.file.name.replace(/\.(pdf|docx)$/i, "");

        if (!githubUsername && profileUrls.length === 0 && !candidate.linkedinUrl.trim() && !candidate.twitterHandle.trim() && !candidateName.trim()) {
          throw new Error("Add at least one public profile link, handle, or candidate name for social evidence.");
        }

        const social = await api.analyzeSocial({
          candidateEmail,
          candidateName,
          githubUsername,
          linkedinUrl: candidate.linkedinUrl,
          twitterHandle: candidate.twitterHandle,
          profileUrls,
          approvedProfileUrls: candidate.approvedProfileUrls,
          rejectedProfileUrls: candidate.rejectedProfileUrls,
          webDiscoveryEnabled: candidate.webDiscoveryEnabled,
          firecrawlEnabled: candidate.firecrawlEnabled,
          consentConfirmed: candidate.consentConfirmed,
          claimedSkills: resume.extracted_data.skills.slice(0, 30),
          signal
        });

        updateCandidate(candidate.id, {
          social,
          status: "evaluating",
          progress: 78,
          activeStep: "Combining resume and social scores"
        });
        appendLog(candidate.id, `Social score ${social.social_score.toFixed(1)}`);
        social.audit_events
          .filter((event) => ["provider", "evidence", "warning"].includes(event.stage))
          .slice(0, 8)
          .forEach((event) => appendLog(candidate.id, `${event.provider ? `${event.provider}: ` : ""}${event.message}`));

        const evaluation = await api.evaluateCandidate({
          resumeScore: resume.total_score,
          socialScore: social.social_score,
          candidateName,
          candidateEmail,
          jobTitle,
          signal
        });

        updateCandidate(candidate.id, {
          evaluation,
          status: "completed",
          progress: 100,
          activeStep: "Completed",
          completedAt: Date.now()
        });
        appendLog(candidate.id, `Final score ${evaluation.report.weighted_total.toFixed(1)} (${evaluation.report.tier.tier})`);
      } catch (error) {
        const wasCancelled = signal.aborted || (error instanceof DOMException && error.name === "AbortError");
        const message =
          wasCancelled
            ? "Run cancelled"
            : error instanceof ApiError
              ? `${error.message} (${error.status})`
              : error instanceof Error
                ? error.message
                : "Unknown error";

        updateCandidate(candidate.id, {
          status: wasCancelled ? "cancelled" : "failed",
          progress: wasCancelled ? 0 : 100,
          activeStep: wasCancelled ? "Cancelled" : "Failed",
          error: message,
          completedAt: Date.now()
        });
        appendLog(candidate.id, message);
      }
    },
    [api, appendLog, jobDescription, jobTitle, updateCandidate]
  );

  const runAllCandidates = async () => {
    setGlobalMessage("");

    if (candidates.length === 0) {
      setGlobalMessage("Add at least one PDF or DOCX resume first.");
      return;
    }

    if (!apiKey.trim()) {
      setGlobalMessage("Add your API key before running candidates.");
      return;
    }

    if (jobDescription.trim().length < 10) {
      setGlobalMessage("Job description must be at least 10 characters.");
      return;
    }

    const runnable = candidates.filter((candidate) => !runningStatuses.includes(candidate.status));
    if (runnable.length === 0) {
      setGlobalMessage("All candidates are already running.");
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsRunning(true);

    const runnableIds = new Set(runnable.map((candidate) => candidate.id));
    setCandidates((current) =>
      current.map((candidate) =>
        runnableIds.has(candidate.id)
          ? {
              ...candidate,
              status: "queued",
              progress: 0,
              activeStep: "Queued for parallel run",
              error: undefined,
              logs: [...candidate.logs, `${new Date().toLocaleTimeString()} · Queued for parallel run`]
            }
          : candidate
      )
    );

    let index = 0;
    const workerCount = Math.max(1, Math.min(concurrency, runnable.length));
    const workers = Array.from({ length: workerCount }, async () => {
      while (index < runnable.length && !controller.signal.aborted) {
        const candidate = runnable[index];
        index += 1;
        await runCandidate(candidate, controller.signal);
      }
    });

    await Promise.all(workers);
    setIsRunning(false);
    abortControllerRef.current = null;
    if (!controller.signal.aborted) {
      setGlobalMessage(`Finished running ${runnable.length} candidate session${runnable.length === 1 ? "" : "s"}.`);
    }
  };

  const stopAll = () => {
    abortControllerRef.current?.abort();
    setIsRunning(false);
    setCandidates((current) =>
      current.map((candidate) =>
        runningStatuses.includes(candidate.status)
          ? {
              ...candidate,
              status: "cancelled",
              activeStep: "Cancelled",
              progress: 0,
              error: "Run cancelled",
              completedAt: Date.now()
            }
          : candidate
      )
    );
  };

  const completed = candidates.filter((candidate) => candidate.status === "completed");
  const failed = candidates.filter((candidate) => candidate.status === "failed");
  const active = candidates.filter((candidate) => runningStatuses.includes(candidate.status));

  const rankedCandidates = useMemo(
    () =>
      [...candidates].sort(
        (left, right) =>
          (right.evaluation?.report.weighted_total ?? -1) - (left.evaluation?.report.weighted_total ?? -1)
      ),
    [candidates]
  );

  const averageFinalScore = completed.length
    ? completed.reduce((sum, candidate) => sum + (candidate.evaluation?.report.weighted_total ?? 0), 0) / completed.length
    : 0;

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">HireSignal ATS</p>
          <h1>Parallel candidate screening dashboard</h1>
          <p className="hero-copy">
            Upload multiple resumes, add each candidate’s social handles, and run independent end-to-end scoring sessions
            against the FastAPI backend.
          </p>
        </div>
        <div className="hero-actions">
          <button className="button secondary" onClick={checkHealth} type="button">
            Check backend
          </button>
          <a className="button ghost" href={`${apiBaseUrl.replace(/\/$/, "")}/docs`} target="_blank" rel="noreferrer">
            Open API docs
          </a>
        </div>
      </section>

      <section className="status-grid">
        <MetricCard label="Candidates" value={String(candidates.length)} detail={`${active.length} running`} />
        <MetricCard label="Completed" value={String(completed.length)} detail={`${failed.length} failed`} />
        <MetricCard label="Average final score" value={completed.length ? averageFinalScore.toFixed(1) : "—"} detail="Completed only" />
        <div className={`health-card ${health?.status ?? healthError ? "visible" : ""}`}>
          <span className={`health-dot ${health?.status ?? "down"}`} />
          <div>
            <strong>{health ? `Backend ${health.status}` : "Backend not connected"}</strong>
            <p>{health ? Object.entries(health.services).map(([name, status]) => `${name}: ${status}`).join(" · ") : healthError || "Not checked yet"}</p>
          </div>
        </div>
      </section>

      <section className="panel config-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Setup</p>
            <h2>Backend, job, and parallelism</h2>
          </div>
          <div className="run-controls">
            <label>
              Parallel sessions
              <input
                min={1}
                max={10}
                type="number"
                value={concurrency}
                onChange={(event) => setConcurrency(Math.max(1, Math.min(10, Number(event.target.value) || 1)))}
              />
            </label>
            {isRunning ? (
              <button className="button danger" onClick={stopAll} type="button">
                Stop all
              </button>
            ) : (
              <button className="button primary" onClick={() => void runAllCandidates()} type="button">
                Run all sessions
              </button>
            )}
          </div>
        </div>

        <ProviderStatusStrip providers={providerStatuses} />

        <div className="form-grid">
          <label>
            API base URL
            <input value={apiBaseUrl} onChange={(event) => setApiBaseUrl(event.target.value)} placeholder="http://127.0.0.1:8000" />
          </label>
          <label>
            API key
            <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="X-API-Key" type="password" />
          </label>
          <label>
            Job title
            <input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} placeholder="Senior Backend Engineer" />
          </label>
        </div>

        <label className="wide-label">
          Job description
          <textarea value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} rows={7} />
        </label>
      </section>

      <section className="panel upload-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Candidate intake</p>
            <h2>Upload resumes and add social handles</h2>
          </div>
          <div className="compact-actions">
            <button className="button secondary" onClick={clearFinished} type="button" disabled={isRunning}>
              Clear finished
            </button>
            <button className="button secondary" onClick={() => setCandidates([])} type="button" disabled={isRunning || candidates.length === 0}>
              Clear all
            </button>
          </div>
        </div>

        <div className="intake-layout">
          <label
            className={`drop-zone ${isDragging ? "dragging" : ""}`}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
          >
            <input accept=".pdf,.docx" multiple type="file" onChange={handleFileInput} />
            <span className="drop-icon">↥</span>
            <strong>Drop resumes here</strong>
            <small>or click to choose multiple PDF/DOCX files</small>
          </label>

          <div className="bulk-box">
            <label>
              Bulk GitHub usernames
              <textarea
                value={bulkHandles}
                onChange={(event) => setBulkHandles(event.target.value)}
                placeholder={"one username per line\nfirst line maps to first resume"}
                rows={6}
              />
            </label>
            <button className="button secondary" onClick={applyBulkHandles} type="button" disabled={candidates.length === 0}>
              Apply handles in order
            </button>
          </div>
        </div>

        {globalMessage ? <p className="notice">{globalMessage}</p> : null}
      </section>

      <section className="candidate-grid">
        {candidates.length === 0 ? (
          <div className="empty-state">
            <strong>No candidates yet.</strong>
            <p>Add a batch of resumes and you’ll see one editable session card per candidate.</p>
          </div>
        ) : (
          candidates.map((candidate) => (
            <CandidateCard
              candidate={candidate}
              key={candidate.id}
              onChange={(patch) => updateCandidate(candidate.id, patch)}
              onRemove={() => removeCandidate(candidate.id)}
              onReset={() => resetCandidate(candidate.id)}
            />
          ))
        )}
      </section>

      <section className="panel results-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Results</p>
            <h2>Ranked candidate reports</h2>
          </div>
          <div className="compact-actions">
            <button
              className="button secondary"
              disabled={candidates.length === 0}
              onClick={() => downloadCsv("hiresignal-candidates.csv", candidates)}
              type="button"
            >
              Export CSV
            </button>
            <button
              className="button secondary"
              disabled={candidates.length === 0}
              onClick={() => downloadJson("hiresignal-candidates.json", candidates.map(serializeCandidate))}
              type="button"
            >
              Export JSON
            </button>
          </div>
        </div>

        <div className="ranking-list">
          {rankedCandidates.filter((candidate) => candidate.evaluation || candidate.error).length === 0 ? (
            <p className="muted">Run candidates to generate ranked reports.</p>
          ) : (
            rankedCandidates
              .filter((candidate) => candidate.evaluation || candidate.error)
              .map((candidate, index) => <ResultRow candidate={candidate} index={index + 1} key={candidate.id} />)
          )}
        </div>
      </section>
    </main>
  );
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function ProviderStatusStrip({ providers }: { providers: ProviderStatus[] }) {
  if (providers.length === 0) {
    return (
      <div className="provider-strip">
        <span className="provider-pill muted">Provider status unavailable</span>
      </div>
    );
  }

  return (
    <div className="provider-strip" aria-label="Evidence provider status">
      {providers.map((provider) => (
        <span className={`provider-pill ${providerTone(provider.status)}`} title={provider.detail} key={provider.provider}>
          {provider.provider}: {provider.status.replace("_", " ")}
        </span>
      ))}
    </div>
  );
}

function CandidateCard({
  candidate,
  onChange,
  onRemove,
  onReset
}: {
  candidate: CandidateSession;
  onChange: (patch: Partial<CandidateSession>) => void;
  onRemove: () => void;
  onReset: () => void;
}) {
  const isLocked = runningStatuses.includes(candidate.status);
  const report = candidate.evaluation?.report;
  const socialUsernames = socialUsernamesForCandidate(candidate);

  return (
    <article className={`candidate-card ${candidate.status}`}>
      <div className="candidate-header">
        <div>
          <p className="file-name">{candidate.file.name}</p>
          <span className={`pill ${candidate.status}`}>{statusLabel(candidate.status)}</span>
        </div>
        <div className="candidate-actions">
          <button className="icon-button" onClick={onReset} type="button" disabled={isLocked}>
            Reset
          </button>
          <button className="icon-button danger-text" onClick={onRemove} type="button" disabled={isLocked}>
            Remove
          </button>
        </div>
      </div>

      <div className="progress-track" aria-label={`${candidate.progress}% complete`}>
        <span style={{ width: `${candidate.progress}%` }} />
      </div>
      <p className="active-step">{candidate.activeStep}</p>

      <div className="candidate-fields">
        <label>
          GitHub username
          <input
            disabled={isLocked}
            value={candidate.githubUsername}
            onChange={(event) => onChange({ githubUsername: event.target.value })}
            placeholder="torvalds"
          />
        </label>
        <label>
          Email override
          <input
            disabled={isLocked}
            value={candidate.emailOverride}
            onChange={(event) => onChange({ emailOverride: event.target.value })}
            placeholder="optional"
          />
        </label>
        <label>
          Name override
          <input
            disabled={isLocked}
            value={candidate.nameOverride}
            onChange={(event) => onChange({ nameOverride: event.target.value })}
            placeholder="optional"
          />
        </label>
        <label>
          LinkedIn URL
          <input
            disabled={isLocked}
            value={candidate.linkedinUrl}
            onChange={(event) => onChange({ linkedinUrl: event.target.value })}
            placeholder="optional"
          />
        </label>
        <label>
          Twitter/X handle
          <input
            disabled={isLocked}
            value={candidate.twitterHandle}
            onChange={(event) => onChange({ twitterHandle: event.target.value })}
            placeholder="optional"
          />
        </label>
      </div>

      <SocialUsernamesPanel profiles={socialUsernames} />

      <details className="review-controls">
        <summary>Review controls, privacy, and profile allowlist</summary>
        <div className="toggle-grid">
          <label className="checkbox-label">
            <input
              checked={candidate.consentConfirmed}
              disabled={isLocked}
              type="checkbox"
              onChange={(event) => onChange({ consentConfirmed: event.target.checked })}
            />
            Public-data screening consent confirmed
          </label>
          <label className="checkbox-label">
            <input
              checked={candidate.webDiscoveryEnabled}
              disabled={isLocked}
              type="checkbox"
              onChange={(event) => onChange({ webDiscoveryEnabled: event.target.checked })}
            />
            Discover missing profiles with Brave Search
          </label>
          <label className="checkbox-label">
            <input
              checked={candidate.firecrawlEnabled}
              disabled={isLocked}
              type="checkbox"
              onChange={(event) => onChange({ firecrawlEnabled: event.target.checked })}
            />
            Extract public pages with Firecrawl
          </label>
        </div>
        <div className="profile-review-grid">
          <label>
            Approved profile URLs
            <textarea
              disabled={isLocked}
              value={candidate.approvedProfileUrls.join("\n")}
              onChange={(event) => onChange({ approvedProfileUrls: linesFromTextarea(event.target.value) })}
              placeholder={"one URL per line\nused as trusted candidate-owned profiles"}
              rows={3}
            />
          </label>
          <label>
            Rejected profile URLs
            <textarea
              disabled={isLocked}
              value={candidate.rejectedProfileUrls.join("\n")}
              onChange={(event) => onChange({ rejectedProfileUrls: linesFromTextarea(event.target.value) })}
              placeholder={"one URL per line\nexcluded from scoring"}
              rows={3}
            />
          </label>
        </div>
      </details>

      <div className="score-row">
        <ScoreBadge label="Resume" score={candidate.resume?.total_score} />
        <ScoreBadge label="Social" score={candidate.social?.social_score} />
        <ScoreBadge label="Final" score={report?.weighted_total} />
      </div>

      {report ? (
        <div className="mini-report">
          <strong>{report.tier.tier} · {report.tier.label}</strong>
          <p>{report.tier.recommendation}</p>
        </div>
      ) : null}

      {candidate.error ? <p className="error-box">{candidate.error}</p> : null}

      {candidate.social ? <EvidencePanel candidate={candidate} onChange={onChange} /> : null}

      {(candidate.resume?.warnings.length || candidate.social?.warnings.length) ? (
        <details className="warnings">
          <summary>Warnings</summary>
          <ul>
            {[...(candidate.resume?.warnings ?? []), ...(candidate.social?.warnings ?? [])].map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      ) : null}

      <details className="logs">
        <summary>Session log · {candidateRuntime(candidate)}</summary>
        <ul>
          {candidate.logs.map((log, index) => (
            <li key={`${log}-${index}`}>{log}</li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function ScoreBadge({ label, score }: { label: string; score?: number }) {
  return (
    <div className={`score-badge ${scoreTone(score)}`}>
      <span>{label}</span>
      <strong>{score === undefined ? "—" : score.toFixed(1)}</strong>
    </div>
  );
}

type SocialUsername = {
  platform: string;
  username: string;
  url: string;
  source: string;
  status: string;
};

function SocialUsernamesPanel({ profiles }: { profiles: SocialUsername[] }) {
  return (
    <section className="social-usernames">
      <div className="mini-section-heading">
        <strong>Social usernames</strong>
        <span>{profiles.length ? `${profiles.length} detected` : "none detected yet"}</span>
      </div>
      {profiles.length ? (
        <div className="username-grid">
          {profiles.map((profile) => (
            <a
              className={`username-chip ${profile.status}`}
              href={profile.url}
              target="_blank"
              rel="noreferrer"
              title={`${profile.source} · ${profile.status}`}
              key={`${profile.platform}-${profile.username}-${profile.url}`}
            >
              <span>{platformLabel(profile.platform)}</span>
              <strong>{profile.username}</strong>
              <small>{profile.source}</small>
            </a>
          ))}
        </div>
      ) : (
        <p className="muted compact-text">Run the candidate or add profile URLs to show detected handles.</p>
      )}
    </section>
  );
}

function EvidencePanel({
  candidate,
  onChange
}: {
  candidate: CandidateSession;
  onChange: (patch: Partial<CandidateSession>) => void;
}) {
  const social = candidate.social;
  if (!social) return null;

  const discoveredLinks = social.evidence_profiles
    .filter((item) => item.platform === "brave_search")
    .flatMap((item) => item.links);
  const firecrawlCount = social.evidence_profiles.filter((item) => item.source_type === "firecrawl").length;
  const apiCount = social.evidence_profiles.filter((item) => item.source_type === "public_api").length;
  const skippedCount = social.evidence_profiles.filter((item) => !item.retrieved).length;

  const approveUrl = (url: string) => {
    onChange({
      approvedProfileUrls: addUnique(candidate.approvedProfileUrls, url),
      rejectedProfileUrls: candidate.rejectedProfileUrls.filter((item) => item !== url)
    });
  };

  const rejectUrl = (url: string) => {
    onChange({
      rejectedProfileUrls: addUnique(candidate.rejectedProfileUrls, url),
      approvedProfileUrls: candidate.approvedProfileUrls.filter((item) => item !== url)
    });
  };

  return (
    <details className="evidence-panel">
      <summary>Evidence, sources, and scoring transparency</summary>

      <div className="evidence-kpis">
        <MiniStat label="API sources" value={String(apiCount)} />
        <MiniStat label="Firecrawl pages" value={String(firecrawlCount)} />
        <MiniStat label="Skipped/blocked" value={String(skippedCount)} />
        <MiniStat label="Identity" value={`${Math.round(social.identity_match.score * 100)}%`} />
      </div>

      <div className="evidence-section">
        <strong>Provider usage</strong>
        <div className="provider-strip compact">
          {social.provider_statuses.map((provider) => (
            <span className={`provider-pill ${providerTone(provider.status)}`} title={provider.detail} key={provider.provider}>
              {provider.provider}: {provider.status.replace("_", " ")}
            </span>
          ))}
        </div>
      </div>

      <div className="evidence-section">
        <strong>Score breakdown</strong>
        <div className="component-list">
          {social.score_breakdown.components.map((component) => (
            <div className="score-component" key={component.name}>
              <div>
                <span>{component.name}</span>
                <small>{component.detail}</small>
              </div>
              <strong>{component.score.toFixed(1)} / {component.max_score.toFixed(0)}</strong>
            </div>
          ))}
        </div>
      </div>

      <div className="evidence-section">
        <strong>Identity match</strong>
        <p className="muted">
          {social.identity_match.level} confidence · {Math.round(social.identity_match.score * 100)}%
        </p>
        <div className="signal-list">
          {social.identity_match.signals.map((signal) => (
            <span className={`signal-chip ${signal.status}`} title={signal.detail} key={signal.label}>
              {signal.label}: {signal.status.replace("_", " ")}
            </span>
          ))}
        </div>
        {social.identity_match.warnings.map((warning) => (
          <p className="inline-warning" key={warning}>{warning}</p>
        ))}
      </div>

      {discoveredLinks.length > 0 ? (
        <div className="evidence-section">
          <strong>Manual review queue</strong>
          <div className="review-list">
            {discoveredLinks.map((url) => (
              <div className="review-url" key={url}>
                <a href={url} target="_blank" rel="noreferrer">{url}</a>
                <div>
                  <button className="mini-button" type="button" onClick={() => approveUrl(url)}>Approve</button>
                  <button className="mini-button danger-text" type="button" onClick={() => rejectUrl(url)}>Reject</button>
                </div>
              </div>
            ))}
          </div>
          <p className="muted">Approve/reject, then reset and rerun the candidate to apply the review decision.</p>
        </div>
      ) : null}

      <div className="evidence-section">
        <strong>Evidence profiles</strong>
        <div className="evidence-list">
          {social.evidence_profiles.map((item) => (
            <article className={`evidence-item ${item.retrieved ? "retrieved" : "skipped"}`} key={`${item.platform}-${item.url}`}>
              <div className="evidence-topline">
                <span className={`pill ${item.retrieved ? "completed" : "failed"}`}>{item.platform}</span>
                <span className="source-tag">{item.source_type.replace("_", " ")}</span>
                <span>{Math.round(item.confidence * 100)}% confidence</span>
              </div>
              <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a>
              <p>{item.citation || item.summary || item.warnings[0] || "No citation returned."}</p>
              {item.skills.length > 0 ? <small>Skills: {item.skills.slice(0, 10).join(", ")}</small> : null}
              {Object.keys(item.metrics).length > 0 ? (
                <small>Metrics: {formatMetrics(item.metrics)}</small>
              ) : null}
            </article>
          ))}
        </div>
      </div>

      <div className="evidence-section">
        <strong>Source citations</strong>
        <ul className="citation-list">
          {social.source_citations.slice(0, 12).map((citation) => (
            <li key={`${citation.platform}-${citation.url}-${citation.label}`}>
              <a href={citation.url} target="_blank" rel="noreferrer">{citation.label}</a>
              <span>{citation.excerpt}</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="evidence-section">
        <strong>Audit trail</strong>
        <ul className="audit-list">
          {social.audit_events.slice(0, 16).map((event, index) => (
            <li className={eventTone(event.status)} key={`${event.stage}-${index}`}>
              {event.provider ? `${event.provider}: ` : ""}{event.message}
            </li>
          ))}
        </ul>
      </div>

      <div className="evidence-section privacy-box">
        <strong>Privacy and compliance</strong>
        <ul>
          {social.privacy_notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </div>

      <button
        className="button secondary"
        type="button"
        onClick={() => downloadJson(`${candidate.file.name.replace(/\.(pdf|docx)$/i, "")}-report.json`, serializeCandidate(candidate))}
      >
        Export candidate report
      </button>
    </details>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="mini-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ResultRow({ candidate, index }: { candidate: CandidateSession; index: number }) {
  const report = candidate.evaluation?.report;

  if (!report) {
    return (
      <article className="result-row failed">
        <span className="rank">#{index}</span>
        <div>
          <strong>{candidate.file.name}</strong>
          <p>{candidate.error}</p>
        </div>
        <span className="pill failed">Failed</span>
      </article>
    );
  }

  return (
    <article className="result-row">
      <span className="rank">#{index}</span>
      <div className="result-main">
        <div className="result-topline">
          <strong>{report.candidate_name || candidate.file.name}</strong>
          <span className={`score-chip ${scoreTone(report.weighted_total)}`}>{report.weighted_total.toFixed(1)}</span>
          <span className="pill completed">{report.tier.tier}</span>
        </div>
        <p>{report.conclusion}</p>
        <div className="result-meta">
          <span>Resume {report.resume_score.toFixed(1)}</span>
          <span>Social {report.social_score.toFixed(1)}</span>
          <span>Runtime {candidateRuntime(candidate)}</span>
          <span>Eval {formatMs(candidate.evaluation?.processing_time_ms)}</span>
        </div>
        <details>
          <summary>Strengths, concerns, and next steps</summary>
          <div className="details-grid">
            <div>
              <strong>Strengths</strong>
              <ul>
                {report.strengths.map((strength) => (
                  <li key={strength}>{strength}</li>
                ))}
              </ul>
            </div>
            <div>
              <strong>Concerns</strong>
              {report.concerns.length ? (
                <ul>
                  {report.concerns.map((concern) => (
                    <li key={concern}>{concern}</li>
                  ))}
                </ul>
              ) : (
                <p className="muted">No major concerns returned.</p>
              )}
            </div>
            <div>
              <strong>Next steps</strong>
              <p>{report.next_steps}</p>
            </div>
          </div>
        </details>
      </div>
    </article>
  );
}

function linesFromTextarea(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function addUnique(values: string[], next: string): string[] {
  return values.includes(next) ? values : [...values, next];
}

function formatMetrics(metrics: Record<string, unknown>): string {
  return Object.entries(metrics)
    .slice(0, 6)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

function providerTone(status: string): "high" | "medium" | "low" | "muted" {
  if (status === "used" || status === "ready") return "high";
  if (status === "missing_key" || status === "error") return "low";
  if (status === "disabled" || status === "skipped") return "medium";
  return "muted";
}

function eventTone(status: string): "event-success" | "event-warning" | "event-muted" {
  if (status === "success") return "event-success";
  if (status === "warning" || status === "error") return "event-warning";
  return "event-muted";
}

function socialUsernamesForCandidate(candidate: CandidateSession): SocialUsername[] {
  const profiles: SocialUsername[] = [];

  const addProfile = (profile: SocialUsername) => {
    if (!profile.username) return;
    const key = `${profile.platform.toLowerCase()}:${profile.username.toLowerCase()}`;
    if (profiles.some((existing) => `${existing.platform.toLowerCase()}:${existing.username.toLowerCase()}` === key)) {
      return;
    }
    profiles.push(profile);
  };

  const github = candidate.githubUsername.trim().replace(/^@/, "");
  if (github) {
    addProfile({ platform: "github", username: github, url: `https://github.com/${github}`, source: "manual", status: "manual" });
  }
  const linkedIn = profileFromUrl(candidate.linkedinUrl);
  if (linkedIn) addProfile({ ...linkedIn, source: "manual", status: "manual" });
  const twitter = candidate.twitterHandle.trim().replace(/^@/, "");
  if (twitter) {
    addProfile({ platform: "twitter", username: `@${twitter}`, url: `https://x.com/${twitter}`, source: "manual", status: "manual" });
  }

  for (const url of candidate.resume?.extracted_data.profile_urls ?? []) {
    const parsed = profileFromUrl(url);
    if (parsed) addProfile({ ...parsed, source: "resume", status: "found" });
  }

  for (const url of candidate.approvedProfileUrls) {
    const parsed = profileFromUrl(url);
    if (parsed) addProfile({ ...parsed, source: "approved", status: "approved" });
  }

  for (const item of candidate.social?.evidence_profiles ?? []) {
    if (item.platform === "brave_search") {
      for (const link of item.links) {
        const parsed = profileFromUrl(link);
        if (parsed) addProfile({ ...parsed, source: "search", status: "found" });
      }
      continue;
    }
    const parsed = item.username
      ? {
          platform: item.platform,
          username: item.platform === "twitter" && !item.username.startsWith("@") ? `@${item.username}` : item.username,
          url: item.url || profileUrl(item.platform, item.username)
        }
      : profileFromUrl(item.url);
    if (parsed) {
      addProfile({
        ...parsed,
        source: item.source_type.replace("_", " "),
        status: item.retrieved ? "checked" : "skipped"
      });
    }
  }

  return profiles;
}

function profileFromUrl(value: string): Omit<SocialUsername, "source" | "status"> | null {
  if (!value.trim()) return null;
  try {
    const parsed = new URL(value.startsWith("http") ? value : `https://${value}`);
    const host = parsed.hostname.replace(/^www\./, "").toLowerCase();
    const parts = parsed.pathname.split("/").filter(Boolean);
    let platform = "";
    let username = "";

    if (host === "github.com") {
      platform = "github";
      username = parts[0] ?? "";
    } else if (host === "linkedin.com" && parts[0] === "in") {
      platform = "linkedin";
      username = parts[1] ?? "";
    } else if (host === "x.com" || host === "twitter.com") {
      platform = "twitter";
      username = parts[0] ? `@${parts[0]}` : "";
    } else if (host === "huggingface.co") {
      platform = "huggingface";
      username = ["models", "datasets", "spaces"].includes(parts[0] ?? "") ? parts[1] ?? "" : parts[0] ?? "";
    } else if (host === "kaggle.com") {
      platform = "kaggle";
      username = parts[0] ?? "";
    } else if (host === "leetcode.com") {
      platform = "leetcode";
      username = ["u", "profile"].includes(parts[0] ?? "") ? parts[1] ?? "" : parts[0] ?? "";
    } else if (host === "hackerrank.com") {
      platform = "hackerrank";
      username = parts[0] ?? "";
    } else if (host === "codechef.com") {
      platform = "codechef";
      username = parts[0] === "users" ? parts[1] ?? "" : parts[0] ?? "";
    } else if (host === "codeforces.com") {
      platform = "codeforces";
      username = ["profile", "users"].includes(parts[0] ?? "") ? parts[1] ?? "" : parts[0] ?? "";
    }

    if (!platform || !username || ["topics", "orgs", "users", "problems", "contest", "login", "signup"].includes(username.toLowerCase())) {
      return null;
    }
    return { platform, username, url: profileUrl(platform, username.replace(/^@/, "")) || parsed.toString() };
  } catch {
    return null;
  }
}

function profileUrl(platform: string, username: string): string {
  const clean = username.replace(/^@/, "");
  const urls: Record<string, string> = {
    github: `https://github.com/${clean}`,
    linkedin: `https://www.linkedin.com/in/${clean}`,
    twitter: `https://x.com/${clean}`,
    huggingface: `https://huggingface.co/${clean}`,
    kaggle: `https://www.kaggle.com/${clean}`,
    leetcode: `https://leetcode.com/u/${clean}`,
    hackerrank: `https://www.hackerrank.com/${clean}`,
    codechef: `https://www.codechef.com/users/${clean}`,
    codeforces: `https://codeforces.com/profile/${clean}`
  };
  return urls[platform] ?? "";
}

function platformLabel(platform: string): string {
  const labels: Record<string, string> = {
    github: "GitHub",
    linkedin: "LinkedIn",
    twitter: "X",
    huggingface: "Hugging Face",
    kaggle: "Kaggle",
    leetcode: "LeetCode",
    hackerrank: "HackerRank",
    codechef: "CodeChef",
    codeforces: "Codeforces"
  };
  return labels[platform] ?? platform;
}

export default App;
