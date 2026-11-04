import type { ReactNode } from "react";

export type AgentGlyph =
  | "market"
  | "form"
  | "tactical"
  | "availability"
  | "context"
  | "base-rates"
  | "red-team"
  | "judge"
  | "risk"
  | "generic";

export const AGENT_GLYPHS: Record<string, AgentGlyph> = {
  market_agent: "market",
  form_agent: "form",
  tactical_agent: "tactical",
  availability_agent: "availability",
  context_agent: "context",
  base_rate_agent: "base-rates",
  red_team_agent: "red-team",
  judge_agent: "judge",
  risk_agent: "risk",
};

function glyphMark(glyph: AgentGlyph): ReactNode {
  switch (glyph) {
    case "market":
      return (
        <>
          <polyline points="29,58 33,53 37,56 43,49" />
          <polyline points="40,49 43,49 43,52" />
        </>
      );
    case "form":
      return (
        <>
          <line x1="30" y1="58" x2="30" y2="52" />
          <line x1="36" y1="58" x2="36" y2="49" />
          <line x1="42" y1="58" x2="42" y2="54" />
        </>
      );
    case "tactical":
      return (
        <>
          <rect x="29" y="49" width="14" height="10" />
          <line x1="36" y1="49" x2="36" y2="59" />
          <circle cx="36" cy="54" r="2" />
        </>
      );
    case "availability":
      return (
        <>
          <line x1="32" y1="54" x2="40" y2="54" />
          <line x1="36" y1="50" x2="36" y2="58" />
        </>
      );
    case "context":
      return (
        <>
          <circle cx="36" cy="54" r="5" />
          <line x1="33" y1="57" x2="38.5" y2="51.5" />
        </>
      );
    case "base-rates":
      return (
        <>
          <line x1="29" y1="58" x2="29" y2="55" />
          <line x1="33.5" y1="58" x2="33.5" y2="51" />
          <line x1="38.5" y1="58" x2="38.5" y2="53" />
          <line x1="43" y1="58" x2="43" y2="49.5" />
        </>
      );
    case "red-team":
      return (
        <>
          <circle cx="36" cy="54" r="5" />
          <line x1="36" y1="47.5" x2="36" y2="50" />
          <line x1="36" y1="58" x2="36" y2="60.5" />
          <line x1="29.5" y1="54" x2="32" y2="54" />
          <line x1="40" y1="54" x2="42.5" y2="54" />
        </>
      );
    case "judge":
      return (
        <g className="agent-sprite__wave">
          <rect className="agent-sprite__wave-bar" x="30" y="53" width="2" height="5" />
          <rect className="agent-sprite__wave-bar" x="34" y="50" width="2" height="8" />
          <rect className="agent-sprite__wave-bar" x="38" y="52" width="2" height="6" />
          <rect className="agent-sprite__wave-bar" x="42" y="51" width="2" height="7" />
        </g>
      );
    case "risk":
      return (
        <>
          <path d="M36 48.5 L43 51.5 V56 C43 60 39 62 36 63.5 C33 62 29 60 29 56 V51.5 Z" />
          <line className="agent-sprite__scanline" x1="30" y1="52" x2="42" y2="52" />
        </>
      );
    default:
      return (
        <>
          <rect x="32" y="51" width="8" height="8" />
          <line x1="36" y1="49" x2="36" y2="61" />
        </>
      );
  }
}

/**
 * Decorative inline-SVG agent character standing at a desk. The name, scope,
 * kind and phase are rendered as real text by the workflow component; this
 * sprite is hidden from assistive tech and carries no semantic meaning.
 */
export function AgentSprite({
  glyph,
  index = 0,
}: {
  glyph: AgentGlyph;
  index?: number;
}) {
  return (
    <svg
      className="agent-sprite"
      data-agent-index={index}
      data-glyph={glyph}
      viewBox="0 0 72 92"
      aria-hidden="true"
      focusable="false"
    >
      <g className="agent-sprite__figure">
        <line className="agent-sprite__antenna" x1="36" y1="21" x2="36" y2="13" />
        <circle className="agent-sprite__antenna-dot" cx="36" cy="11" r="2.4" />
        {glyph === "red-team" ? (
          <circle className="agent-sprite__scan-ring" cx="36" cy="32" r="16" />
        ) : null}
        <circle className="agent-sprite__head" cx="36" cy="32" r="10.5" />
        <rect className="agent-sprite__visor" x="28.5" y="29" width="15" height="5.5" rx="2" />
        <rect className="agent-sprite__body" x="24" y="43.5" width="24" height="22" rx="2" />
        <g className="agent-sprite__arm agent-sprite__arm--l">
          <line x1="24" y1="48" x2="15" y2="64" />
          <circle cx="15" cy="64" r="1.8" />
        </g>
        <g className="agent-sprite__arm agent-sprite__arm--r">
          <line x1="48" y1="48" x2="57" y2="64" />
          <circle cx="57" cy="64" r="1.8" />
        </g>
        <line className="agent-sprite__desk" x1="9" y1="69" x2="63" y2="69" />
        <g className="agent-sprite__glyph">{glyphMark(glyph)}</g>
      </g>
    </svg>
  );
}
