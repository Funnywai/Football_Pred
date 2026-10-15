import { Info } from "lucide-react";
import type { ReactNode } from "react";

// The shared caption primitive (DESIGN.md 5): one indent, one text token, the Info glyph
// always present, and one placement rule — a Note sits above the content it describes.
export interface NoteProps {
  children: ReactNode;
}

export function Note({ children }: NoteProps) {
  return (
    <p className="flex items-start gap-2 text-caption text-text-tertiary">
      <Info className="mt-0.5 size-3 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  );
}
