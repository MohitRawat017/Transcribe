import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  KeyRound,
  Link as LinkIcon,
  Loader2,
  Play,
  Radio,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";

type AuthStatus = {
  ready: boolean;
  has_client_secret: boolean;
  has_blog_id: boolean;
  has_token: boolean;
  token_valid: boolean;
  message: string;
};

type JobStatus = "queued" | "running" | "succeeded" | "failed";

type Job = {
  id: string;
  status: JobStatus;
  stage: string;
  channel_url: string;
  channel: string | null;
  start: number;
  end: number;
  created_at: string;
  updated_at: string;
  logs: string[];
  error: string | null;
  output_dir: string | null;
};

type PipelineStep = {
  key: string;
  label: string;
  detail: string;
};

const pipelineSteps: PipelineStep[] = [
  { key: "auth", label: "Blogger auth", detail: "credentials and token" },
  { key: "transcript_api", label: "Transcript API", detail: "caption pull first" },
  { key: "whisper_fallback", label: "Whisper fallback", detail: "yt-dlp audio path" },
  { key: "blogify", label: "Blogify", detail: "outline and markdown" },
  { key: "blogger_drafts", label: "Blogger drafts", detail: "HTML draft insert" },
];

const terminalStatuses = new Set<JobStatus>(["succeeded", "failed"]);

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || "Request failed.");
  }
  return payload as T;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error.";
}

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [authBusy, setAuthBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [jobId, setJobId] = useState(() => localStorage.getItem("fetcher.activeJobId") || "");
  const [channelUrl, setChannelUrl] = useState("");
  const [start, setStart] = useState("1");
  const [end, setEnd] = useState("1");
  const [notice, setNotice] = useState("");

  const startNumber = Number(start);
  const endNumber = Number(end);
  const running = job?.status === "queued" || job?.status === "running";
  const rangeValid = Number.isInteger(startNumber) && Number.isInteger(endNumber) && startNumber >= 1 && endNumber >= startNumber;
  const canStart = Boolean(auth?.ready && channelUrl.trim() && rangeValid && !running && !authBusy);

  const activeStage = useMemo(() => {
    if (!auth?.ready) return "auth";
    if (!job) return "";
    if (job.status === "succeeded") return "succeeded";
    return job.stage;
  }, [auth?.ready, job]);

  const activeStepIndex = useMemo(() => {
    if (activeStage === "succeeded") return pipelineSteps.length;
    const index = pipelineSteps.findIndex((step) => step.key === activeStage);
    return index === -1 ? 0 : index;
  }, [activeStage]);

  async function refreshAuth() {
    const nextAuth = await api<AuthStatus>("/api/auth/blogger/status");
    setAuth(nextAuth);
  }

  useEffect(() => {
    refreshAuth().catch((error) => setNotice(errorMessage(error)));
  }, []);

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    async function loadJob() {
      try {
        const nextJob = await api<Job>(`/api/jobs/${jobId}`);
        if (cancelled) return;
        setJob(nextJob);
        if (terminalStatuses.has(nextJob.status)) {
          localStorage.setItem("fetcher.activeJobId", nextJob.id);
        }
      } catch (error) {
        if (cancelled) return;
        setNotice(errorMessage(error));
        localStorage.removeItem("fetcher.activeJobId");
        setJobId("");
      }
    }

    loadJob();
    const timer = window.setInterval(loadJob, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId]);

  async function connectBlogger() {
    setAuthBusy(true);
    setNotice("Opening local Google authorization flow.");
    try {
      const nextAuth = await api<AuthStatus>("/api/auth/blogger/connect", { method: "POST" });
      setAuth(nextAuth);
      setNotice(nextAuth.message);
    } catch (error) {
      setNotice(errorMessage(error));
    } finally {
      setAuthBusy(false);
    }
  }

  async function startJob(event: FormEvent) {
    event.preventDefault();
    if (!canStart) return;

    setNotice("Queueing pipeline job.");
    try {
      const nextJob = await api<Job>("/api/jobs", {
        method: "POST",
        body: JSON.stringify({
          channel_url: channelUrl.trim(),
          start: startNumber,
          end: endNumber,
        }),
      });
      setJob(nextJob);
      setJobId(nextJob.id);
      localStorage.setItem("fetcher.activeJobId", nextJob.id);
      setNotice("Pipeline accepted.");
    } catch (error) {
      setNotice(errorMessage(error));
    }
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand">
          <Radio size={18} aria-hidden="true" />
          <span>Fetcher Control Room</span>
        </div>
        <div className={auth?.ready ? "system-pill online" : "system-pill offline"}>
          {auth?.ready ? <ShieldCheck size={16} /> : <AlertTriangle size={16} />}
          <span>{auth?.ready ? "Blogger linked" : "Blogger gated"}</span>
        </div>
      </header>

      <section className="layout" aria-label="Pipeline controls">
        <form className="intake-panel" onSubmit={startJob}>
          <div className="section-kicker">Intake bay</div>
          <h1>Turn channel range into Blogger drafts.</h1>
          <p className="intro">
            Authentication is checked before the first transcript request. Every run writes into its own isolated workspace.
          </p>

          <label className="field">
            <span>
              <LinkIcon size={16} aria-hidden="true" />
              YouTube channel URL
            </span>
            <input
              value={channelUrl}
              onChange={(event) => setChannelUrl(event.target.value)}
              placeholder="https://www.youtube.com/@channel/videos"
              type="url"
            />
          </label>

          <div className="range-grid">
            <label className="field">
              <span>Start index</span>
              <input min={1} step={1} value={start} onChange={(event) => setStart(event.target.value)} type="number" />
            </label>
            <label className="field">
              <span>End index</span>
              <input min={1} step={1} value={end} onChange={(event) => setEnd(event.target.value)} type="number" />
            </label>
          </div>

          <div className="button-row">
            <button className="secondary" type="button" onClick={connectBlogger} disabled={authBusy || running}>
              {authBusy ? <Loader2 className="spin" size={18} /> : <KeyRound size={18} />}
              <span>{auth?.ready ? "Refresh auth" : "Connect Blogger"}</span>
            </button>
            <button className="primary" type="submit" disabled={!canStart}>
              {running ? <Loader2 className="spin" size={18} /> : <Play size={18} />}
              <span>{running ? "Running" : "Start pipeline"}</span>
            </button>
          </div>

          <div className="status-grid">
            <StatusFlag label="client_secret.json" ready={Boolean(auth?.has_client_secret)} />
            <StatusFlag label="BLOGGER_BLOG_ID" ready={Boolean(auth?.has_blog_id)} />
            <StatusFlag label="token.json" ready={Boolean(auth?.has_token)} />
            <StatusFlag label="token valid" ready={Boolean(auth?.token_valid)} />
          </div>
        </form>

        <aside className="rail-panel" aria-label="Pipeline stages">
          <div className="section-kicker">Pipeline rail</div>
          <div className="rail">
            {pipelineSteps.map((step, index) => {
              const done = activeStepIndex > index || activeStage === "succeeded";
              const active = activeStage === step.key;
              const failed = job?.status === "failed" && active;
              return <RailStep key={step.key} step={step} done={done} active={active} failed={failed} />;
            })}
          </div>
        </aside>
      </section>

      <section className="telemetry" aria-label="Pipeline telemetry">
        <div className="telemetry-head">
          <div>
            <div className="section-kicker">Telemetry tape</div>
            <h2>{job ? job.channel || "Channel resolving" : "No active run"}</h2>
          </div>
          <div className={`job-state ${job?.status || "idle"}`}>
            <Activity size={16} />
            <span>{job?.status || "idle"}</span>
          </div>
        </div>

        {notice && <div className="notice">{notice}</div>}

        <div className="job-meta">
          <span>Range: {job ? `${job.start}-${job.end}` : `${start || "-"}-${end || "-"}`}</span>
          <span>Stage: {job?.stage || (auth?.ready ? "ready" : "auth")}</span>
          <span>Output: {job?.output_dir || "waiting"}</span>
        </div>

        <div className="log-window">
          {job?.logs.length ? (
            job.logs.slice(-160).map((line, index) => (
              <div className="log-line" key={`${index}-${line}`}>
                <TerminalSquare size={14} aria-hidden="true" />
                <span>{line}</span>
              </div>
            ))
          ) : (
            <div className="empty-log">Logs will appear here when the pipeline starts.</div>
          )}
        </div>
      </section>
    </main>
  );
}

function StatusFlag({ label, ready }: { label: string; ready: boolean }) {
  return (
    <div className={ready ? "flag ready" : "flag blocked"}>
      {ready ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} />}
      <span>{label}</span>
    </div>
  );
}

function RailStep({ step, done, active, failed }: { step: PipelineStep; done: boolean; active: boolean; failed: boolean }) {
  return (
    <div className={["rail-step", done ? "done" : "", active ? "active" : "", failed ? "failed" : ""].join(" ")}>
      <div className="rail-node" aria-hidden="true" />
      <div>
        <strong>{step.label}</strong>
        <span>{step.detail}</span>
      </div>
    </div>
  );
}
