import type { ReactNode } from "react";

type PanelVariant = "default" | "accent" | "flush";

const VARIANT_CLASS: Record<PanelVariant, string> = {
  default: "border border-border-default",
  accent: "border-2 border-accent-signal",
  flush: "border border-border-default",
};

export interface PanelProps {
  id: string;
  title: string;
  action?: ReactNode;
  variant?: PanelVariant;
  children: ReactNode;
}

export function Panel({ id, title, action, variant = "default", children }: PanelProps) {
  const titleId = `${id}-title`;
  return (
    <section
      aria-labelledby={titleId}
      className={`rounded-lg bg-surface-base ${VARIANT_CLASS[variant]}`}
    >
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border-hairline px-6 py-4">
        <h2 id={titleId} className="text-h2 font-semibold text-text-primary">
          {title}
        </h2>
        {action}
      </header>
      <div className={variant === "flush" ? "" : "px-6 py-6"}>{children}</div>
    </section>
  );
}
