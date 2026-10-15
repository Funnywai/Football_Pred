import type { ComponentType, ReactNode } from "react";

export interface EmptyStateProps {
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  title: string;
  detail?: string;
  children?: ReactNode;
}

export function EmptyState({ icon: Icon, title, detail, children }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-10 text-center">
      <Icon className="size-5 text-text-tertiary" aria-hidden />
      <p className="text-body text-text-secondary">{title}</p>
      {detail === undefined ? null : <p className="text-caption text-text-tertiary">{detail}</p>}
      {children}
    </div>
  );
}
