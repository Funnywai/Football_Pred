"use client";

import { useId } from "react";

import { Search, X } from "lucide-react";

export interface SearchInputProps {
  label: string;
  scope: string;
  value: string;
  onChange: (next: string) => void;
  onClear: () => void;
}

export function SearchInput({ label, scope, value, onChange, onClear }: SearchInputProps) {
  // useId, never a constant: three of these tables can appear on one page, and duplicate DOM
  // ids would break the label association and make getByLabelText ambiguous.
  const id = useId();
  return (
    <div className="flex flex-wrap items-center gap-3 px-6 py-3">
      <label htmlFor={id} className="flex items-center gap-2 text-body text-text-secondary">
        <Search className="size-3 text-text-tertiary" aria-hidden />
        {label}
      </label>
      <input
        id={id}
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="rounded-md border border-border-default bg-surface-base px-2 py-1 text-body text-text-primary placeholder:text-text-tertiary focus:border-accent-signal focus:outline-none"
      />
      {value === "" ? null : (
        <button
          type="button"
          aria-label="Clear search"
          onClick={onClear}
          className="inline-flex items-center gap-1 rounded-md border border-border-default px-2 py-1 text-caption text-text-secondary transition-colors duration-150 ease-out hover:border-accent-signal/60 hover:text-text-primary"
        >
          <X className="size-3" aria-hidden />
        </button>
      )}
      <span className="text-caption text-text-tertiary">{scope}</span>
    </div>
  );
}
