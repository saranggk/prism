"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

type Connection = "checking" | "connected" | "unavailable";

const apiOrigin = process.env.NEXT_PUBLIC_API_ORIGIN ?? "http://127.0.0.1:8000";

export default function Home() {
  const [api, setApi] = useState<Connection>("checking");
  const [database, setDatabase] = useState<Connection>("checking");
  const [checking, setChecking] = useState(true);

  async function checkConnection(signal?: AbortSignal) {
    try {
      const response = await fetch(`${apiOrigin}/health`, {
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(5000)]) : AbortSignal.timeout(5000),
        cache: "no-store",
      });
      const health = await response.json();
      if (signal?.aborted) return;
      setApi(health.api === "ok" ? "connected" : "unavailable");
      setDatabase(health.database === "ok" ? "connected" : "unavailable");
    } catch {
      if (signal?.aborted) return;
      setApi("unavailable");
      setDatabase("unavailable");
    } finally {
      if (!signal?.aborted) setChecking(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!controller.signal.aborted) void checkConnection(controller.signal);
    });
    return () => controller.abort();
  }, []);

  return (
    <main className="workspace">
      <header className="masthead">
        <Link className="brand" href="/" aria-label="Prism home">
          <span className="brand-mark" aria-hidden="true">◭</span>
          prism<span className="brand-dot">.</span>
        </Link>
        <span className="environment"><span aria-hidden="true" /> Local workspace</span>
      </header>

      <section className="intro" aria-labelledby="page-title">
        <p className="eyebrow">YOUR VIDEO RESEARCH WORKSPACE</p>
        <h1 id="page-title">Find the moment.<br /><span>Keep the context.</span></h1>
        <p className="intro-copy">A home for the details hidden in your tutorials and demos.</p>
      </section>

      <section className="setup-card" aria-labelledby="setup-title">
        <div className="setup-heading">
          <span className="step-number" aria-hidden="true">01</span>
          <div>
            <p className="eyebrow">GETTING STARTED</p>
            <h2 id="setup-title">Your workspace is taking shape</h2>
          </div>
        </div>
        <p className="setup-copy">This first build checks your local connection. Video uploads and search are coming next.</p>
        <div className="connection-list" aria-live="polite" aria-busy={checking}>
          <ConnectionRow label="Backend" state={api} />
          <ConnectionRow label="Database" state={database} />
        </div>
        <div className="card-footer">
          <p>{api === "unavailable" ? "Start the backend, then check again." : database === "unavailable" ? "Start the database, then check again." : "Everything stays on your computer."}</p>
          <button onClick={() => { setChecking(true); void checkConnection(); }} disabled={checking}>
            {checking ? "Checking…" : "Check connection"}<span aria-hidden="true"> ↗</span>
          </button>
        </div>
      </section>

      <footer className="page-footer"><span>PRISM / EARLY BUILD</span><span>Upload → prepare → search → play</span></footer>
    </main>
  );
}

function ConnectionRow({ label, state }: { label: string; state: Connection }) {
  return (
    <div className="connection-row">
      <span>{label}</span>
      <span className={`status status-${state}`}><span aria-hidden="true" />{state === "checking" ? "Checking…" : state === "connected" ? "Connected" : "Unavailable"}</span>
    </div>
  );
}
