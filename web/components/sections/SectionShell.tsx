import { Panel } from "@/components/ui/Panel";
import { StatusPill } from "@/components/ui/StatusPill";

export interface SectionShellProps {
  id: string;
  title: string;
  purpose: string;
  source: string;
}

export function SectionShell({ id, title, purpose, source }: SectionShellProps) {
  return (
    <Panel
      id={id}
      title={title}
      action={<StatusPill variant="queued" label="pending — next increment" />}
    >
      <p className="text-body text-text-secondary">{purpose}</p>
      <p className="mt-2 text-caption text-text-tertiary">
        source <span className="tnum text-text-secondary">{source}</span>
      </p>
    </Panel>
  );
}
