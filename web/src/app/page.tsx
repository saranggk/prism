import Link from "next/link";

import { VideoLibrary } from "@/components/video-library";

export default function Home() {
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

      <VideoLibrary />

      <footer className="page-footer"><span>PRISM / EARLY BUILD</span><span>Upload → prepare → search → play</span></footer>
    </main>
  );
}
