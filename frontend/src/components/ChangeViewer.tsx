"use client";

import { useEffect, useState } from "react";
import type { ChangedFile } from "@/lib/types";
import { Badge, Empty, PanelHeader } from "./ui";

const TYPE_TONE = { added: "green", modified: "amber", deleted: "red" } as const;

export function ChangeViewer({ files }: { files: ChangedFile[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => setSelected(files[0]?.path ?? null), [files]);
  const file = files.find((f) => f.path === selected);

  return (
    <section className="flex min-h-0 flex-col">
      <PanelHeader title="Change" right={<span className="text-[11px] text-slate-500">{files.length} file(s)</span>} />
      {files.length === 0 ? (
        <Empty>Run a scenario to see its diff.</Empty>
      ) : (
        <>
          <ul className="shrink-0 border-b border-white/5 py-1">
            {files.map((f) => (
              <li key={f.path}>
                <button
                  onClick={() => setSelected(f.path)}
                  className={`flex w-full items-center gap-2 px-3 py-1 text-left font-mono text-[12px] ${
                    f.path === selected ? "bg-white/5 text-slate-100" : "text-slate-400 hover:bg-white/[0.03]"
                  }`}
                >
                  <Badge tone={TYPE_TONE[f.change_type]}>{f.change_type[0].toUpperCase()}</Badge>
                  <span className="min-w-0 flex-1 truncate">{f.path}</span>
                  <span className="text-emerald-400">+{f.additions}</span>
                  <span className="text-red-400">−{f.deletions}</span>
                </button>
              </li>
            ))}
          </ul>
          {file && <Diff diff={file.diff} />}
        </>
      )}
    </section>
  );
}

function Diff({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  let oldNo = 0;
  let newNo = 0;
  return (
    <div className="scrollbar-thin min-h-0 flex-1 overflow-auto font-mono text-[11.5px] leading-[1.6]">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            if (line.startsWith("---") || line.startsWith("+++")) return null;
            if (line.startsWith("@@")) {
              const m = /@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
              if (m) {
                oldNo = Number(m[1]);
                newNo = Number(m[2]);
              }
              return (
                <tr key={i} className="bg-sky-500/5 text-sky-300/70">
                  <td colSpan={3} className="px-3 py-0.5">
                    {line}
                  </td>
                </tr>
              );
            }
            const kind = line[0];
            const cls =
              kind === "+" ? "bg-emerald-500/10 text-emerald-100" : kind === "-" ? "bg-red-500/10 text-red-100" : "text-slate-400";
            const left = kind === "+" ? "" : oldNo++;
            const right = kind === "-" ? "" : newNo++;
            return (
              <tr key={i} className={cls}>
                <td className="w-8 select-none pr-1 text-right align-top text-slate-600">{left}</td>
                <td className="w-8 select-none pr-2 text-right align-top text-slate-600">{right}</td>
                <td className="whitespace-pre pr-3">{line || " "}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
