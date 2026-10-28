"use client";

import { useState } from "react";

type Tone = "red" | "amber" | "green" | "blue" | "slate" | "violet";

const TONES: Record<Tone, string> = {
  red: "bg-red-500/10 text-red-300 ring-red-500/30",
  amber: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  green: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  blue: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  violet: "bg-violet-500/10 text-violet-300 ring-violet-500/30",
  slate: "bg-slate-500/10 text-slate-300 ring-slate-500/30",
};

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}

export function PanelHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-b border-white/5 px-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{title}</h2>
      {right}
    </div>
  );
}

export function Code({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <pre
      className={`scrollbar-thin overflow-x-auto whitespace-pre rounded border border-white/5 bg-black/40 p-2 font-mono text-[11.5px] leading-relaxed text-slate-300 ${className}`}
    >
      {children}
    </pre>
  );
}

export function Collapsible({
  label,
  children,
  defaultOpen = false,
}: {
  label: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-[11px] font-medium text-slate-400 hover:text-slate-200"
      >
        <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
        {label}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-3 py-6 text-center text-xs text-slate-500">{children}</div>;
}
