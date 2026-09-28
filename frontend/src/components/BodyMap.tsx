import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { BodySystem, SystemStatus } from "../api/types";
import { fmtNum, fmtUnit, shortName } from "../lib/format";
import { useElementWidth } from "../lib/useWidth";

/**
 * Body map for the Trends page: one continuous outline with the organs behind each body system, coloured by the
 * system's status (amber guideline alert, blue changed, grey stable). Only systems with results are drawn. Hovering an organ highlights
 * its system card and the other way round; clicking opens the system. Colours match the status pills.
 */

// One continuous outline (head, neck, arms, torso), drawn once as a mirrored path in a 240 × 350 box.
const OUTLINE =
  "M120 16 C134 16 146 27 146 43 C146 55 140 64 133 71 L133 83 C149 88 165 90 177 97 C188 104 193 117 194 132 " +
  "L199 242 C200 254 197 263 190 263 C184 263 182 257 182 249 L177 158 C174 170 172 180 172 192 C172 218 176 236 " +
  "176 256 C176 284 172 304 164 322 C150 330 134 334 120 334 C106 334 90 330 76 322 C68 304 64 284 64 256 C64 236 " +
  "68 218 68 192 C68 180 66 170 63 158 L58 249 C58 257 56 263 50 263 C43 263 40 254 41 242 L46 132 C47 117 52 104 " +
  "63 97 C75 90 91 88 107 83 L107 71 C100 64 94 55 94 43 C94 27 106 16 120 16 Z";

interface Organ {
  system: string;
  paths: string[];
  /** Where the leader line leaves the organ, and which side the label sits on. */
  anchor: [number, number];
  side: "left" | "right";
  labelY: number;
  circle?: { cx: number; cy: number; r: number; text: string };
}

const ORGANS: Organ[] = [
  { system: "thyroid", side: "left", labelY: 70, anchor: [108, 82],
    paths: ["M113 78 C108 76 106 82 109 86 C111 89 116 88 118 85 L122 85 C124 88 129 89 131 86 C134 82 132 76 127 78 C124 79 122 81 120 81 C118 81 116 79 113 78 Z"] },
  { system: "lipids", side: "right", labelY: 122, anchor: [145, 132],
    paths: ["M130 128 C126 121 116 122 116 131 C116 140 125 146 131 152 C138 146 146 139 145 130 C144 122 134 121 130 128 Z"] },
  { system: "liver", side: "left", labelY: 158, anchor: [79, 176],
    paths: ["M80 168 C92 160 118 160 132 166 C134 171 128 176 118 180 C106 186 94 192 86 190 C79 186 77 176 80 168 Z"] },
  { system: "glucose", side: "right", labelY: 188, anchor: [152, 190],
    paths: ["M108 197 C116 191 132 189 146 186 C152 185 155 190 150 193 C139 198 125 202 115 204 C108 205 105 201 108 197 Z"] },
  { system: "kidney", side: "left", labelY: 214, anchor: [88, 217],
    paths: ["M96 206 C90 206 87 213 88 221 C89 229 95 233 101 231 C104 230 104 226 102 223 C100 220 101 217 103 215 C106 212 104 206 96 206 Z",
            "M144 206 C150 206 153 213 152 221 C151 229 145 233 139 231 C136 230 136 226 138 223 C140 220 139 217 137 215 C134 212 136 206 144 206 Z"] },
  { system: "blood_count", side: "right", labelY: 252, anchor: [197, 222],
    paths: ["M190 206 C194 212 197 216 197 220 C197 224 194 227 190 227 C186 227 183 224 183 220 C183 216 186 212 190 206 Z"] },
  { system: "electrolytes", side: "left", labelY: 280, anchor: [43, 238], paths: [],
    circle: { cx: 50, cy: 238, r: 7.5, text: "K⁺" } },
];

const STYLE: Record<SystemStatus, { fill: string; stroke: string; hotFill: string; text: string; word: string }> = {
  guideline: { fill: "#FBEBD3", stroke: "#C8741F", hotFill: "#F6D9AE", text: "#8A4507", word: "Guideline alert" },
  changed: { fill: "#E4EEF8", stroke: "#2F6DA3", hotFill: "#CFE0F2", text: "#1F5282", word: "Changed" },
  stable: { fill: "#EFE9DC", stroke: "#8C94A0", hotFill: "#E4DCCB", text: "#3F4855", word: "Stable" },
  no_data: { fill: "transparent", stroke: "#CFC5B2", hotFill: "#F4EEE2", text: "#6A7280", word: "No results" },
};

const OFFSET = 160;          // figure x offset inside the labelled view
const LEFT_X = 150, RIGHT_X = 410;

export function BodyMap({ systems, base, hot, onHot, pulse }: {
  systems: BodySystem[]; base: string; hot: string | null; onHot: (id: string | null) => void; pulse?: string | null;
}) {
  const navigate = useNavigate();
  const [ref, width] = useElementWidth<HTMLDivElement>(560);
  const compact = width < 470;
  const byId = new Map(systems.map((s) => [s.id, s]));
  const view = compact ? `${OFFSET + 20} 8 200 334` : "0 8 560 334";
  const counts = { guideline: 0, changed: 0, stable: 0 };
  systems.forEach((s) => { if (s.status in counts) counts[s.status as keyof typeof counts]++; });

  function open(id: string) {
    const s = byId.get(id);
    if (s && s.status !== "no_data") navigate(`${base}/systems/${id}`);
  }
  function key(e: KeyboardEvent, id: string) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(id); }
  }

  return (
    <section aria-labelledby="bodymap-h" className="flex flex-col gap-3 rounded-[18px] border border-line bg-card px-6 pb-4 pt-5 shadow-soft" data-testid="body-map">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="bodymap-h" className="m-0 font-serif text-[22px] font-medium">Body map</h2>
        <span className="text-[13px] text-ink-3">
          {counts.guideline > 0 && <span className="font-semibold text-amber-ink">{counts.guideline} guideline alert</span>}
          {counts.guideline > 0 && counts.changed + counts.stable > 0 && " · "}
          {[counts.changed && `${counts.changed} changed`, counts.stable && `${counts.stable} stable`].filter(Boolean).join(" · ")}
        </span>
        <div className="grow" />
        <span className="hidden text-xs text-ink-3 sm:inline">Select an organ to open its system</span>
      </div>
      <div ref={ref} className={`relative mx-auto w-full ${compact ? "max-w-[300px]" : "max-w-[680px]"}`}>
        <svg viewBox={view} className="block h-auto w-full" role="group" aria-label="Body map of the patient's systems">
          <defs>
            <linearGradient id="bm-skin" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#FFFDF9" />
              <stop offset="1" stopColor="#F4EEE2" />
            </linearGradient>
            <radialGradient id="bm-floor" cx="0.5" cy="0.5" r="0.5">
              <stop offset="0" stopColor="#1D2733" stopOpacity="0.12" />
              <stop offset="1" stopColor="#1D2733" stopOpacity="0" />
            </radialGradient>
          </defs>
          <g transform={`translate(${OFFSET} 0)`}>
            <ellipse cx="120" cy="336" rx="70" ry="7" fill="url(#bm-floor)" />
            <path d={OUTLINE} fill="url(#bm-skin)" stroke="#B9AE98" strokeWidth="1.4" strokeLinejoin="round" />
          </g>

          {ORGANS.map((o) => {
            const s = byId.get(o.system);
            if (!s || s.status === "no_data") return null;       // only organs with results are drawn
            const st = STYLE[s.status];
            const isHot = hot === o.system;
            const h = s.headline;
            const value = h?.latest ? `${shortName(h.name)} ${h.latest.comparator ?? ""}${fmtNum(h.latest.value)}` : "No results";
            const label = `${s.name}: ${st.word}${h?.latest ? `, ${value} ${fmtUnit(h.unit)}` : ""}. Open system`;
            const [ax, ay] = o.anchor;
            const lx = o.side === "left" ? LEFT_X : RIGHT_X;
            return (
              <g key={o.system} role="link" tabIndex={0} aria-label={label}
                data-testid={`organ-${o.system}`} data-status={s.status}
                onMouseEnter={() => onHot(o.system)} onMouseLeave={() => onHot(null)}
                onFocus={() => onHot(o.system)} onBlur={() => onHot(null)}
                onClick={() => open(o.system)} onKeyDown={(e) => key(e, o.system)}
                className="cursor-pointer outline-none">
                {!compact && (
                  <g aria-hidden="true">
                    <path d={`M${ax + OFFSET} ${ay} L${o.side === "left" ? lx + 6 : lx - 6} ${o.labelY + 4}`}
                      stroke={isHot ? st.stroke : "#CFC5B2"} strokeWidth={isHot ? 1.3 : 1} fill="none" className="organ" />
                    <circle cx={ax + OFFSET} cy={ay} r={2} fill={isHot ? st.stroke : "#B9AE98"} className="organ" />
                    <text x={lx} y={o.labelY} textAnchor={o.side === "left" ? "end" : "start"} fontSize="13" fontWeight="600"
                      fill={isHot ? st.text : "#1D2733"} className="organ" style={{ textDecoration: isHot ? "underline" : undefined }}>
                      {s.status === "guideline" ? "▲ " : ""}{s.name}
                    </text>
                    <text x={lx} y={o.labelY + 16} textAnchor={o.side === "left" ? "end" : "start"} fontSize="12" fill={st.text}
                      style={{ fontVariantNumeric: "tabular-nums" }}>
                      {`${value} · ${st.word.toLowerCase()}`}
                    </text>
                  </g>
                )}
                <g transform={`translate(${OFFSET} 0)`}>
                  {o.paths.map((d) => (
                    <path key={d} d={d} className="organ" fill={isHot ? st.hotFill : st.fill} stroke={st.stroke}
                      strokeWidth={isHot ? 2.2 : 1.6} strokeLinejoin="round" />
                  ))}
                  {o.circle && (
                    <>
                      <circle cx={o.circle.cx} cy={o.circle.cy} r={o.circle.r} className="organ" fill={isHot ? st.hotFill : st.fill}
                        stroke={st.stroke} strokeWidth={isHot ? 2.2 : 1.6} />
                      <text x={o.circle.cx} y={o.circle.cy + 3} textAnchor="middle" fontSize="7.5" fontWeight="600" fill={st.text} aria-hidden="true">{o.circle.text}</text>
                    </>
                  )}
                  {pulse === o.system && o.paths.map((d) => (
                    <path key={"p" + d} d={d} fill="none" stroke={st.stroke} strokeWidth="2" className="organ-pulse" aria-hidden="true" />
                  ))}
                  {isHot && o.paths.map((d) => (
                    <path key={"f" + d} d={d} fill="none" stroke={st.stroke} strokeOpacity="0.25" strokeWidth="6" aria-hidden="true" />
                  ))}
                </g>
              </g>
            );
          })}
        </svg>
      </div>
      {compact && (
        <ul className="m-0 grid list-none grid-cols-2 gap-x-4 gap-y-1.5 p-0 text-[13px]">
          {ORGANS.map((o) => byId.get(o.system)).filter((s) => s && s.status !== "no_data").map((s) => (
            <li key={s!.id} className="flex items-center gap-2">
              <span aria-hidden="true" className="inline-block h-2.5 w-2.5 rounded-full border"
                style={{ background: STYLE[s!.status].fill, borderColor: STYLE[s!.status].stroke }} />
              <span className="text-ink-2">{s!.name}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
