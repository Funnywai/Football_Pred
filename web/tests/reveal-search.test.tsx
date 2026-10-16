import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RevealFooter } from "@/components/ui/RevealFooter";
import { SearchInput } from "@/components/ui/SearchInput";

describe("SearchInput", () => {
  it("has an accessible name and states its scope", () => {
    render(<SearchInput label="Search bets" scope="searches the 200 rows in this window" value="" onChange={() => {}} onClear={() => {}} />);
    expect(screen.getByLabelText("Search bets")).toBeInTheDocument();
    expect(screen.getByText("searches the 200 rows in this window")).toBeInTheDocument();
  });

  it("only shows Clear when non-empty and calls onClear", () => {
    const onClear = vi.fn();
    const { rerender } = render(<SearchInput label="Search bets" scope="s" value="" onChange={() => {}} onClear={onClear} />);
    expect(screen.queryByRole("button", { name: "Clear search" })).not.toBeInTheDocument();
    rerender(<SearchInput label="Search bets" scope="s" value="arsenal" onChange={() => {}} onClear={onClear} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(onClear).toHaveBeenCalledOnce();
  });
});

describe("RevealFooter", () => {
  it("states both counts so the revealed number never reads as a total", () => {
    render(<RevealFooter base="showing the 200 most recent of 250 bets" shown={10} matching={200} isFiltered={false} canExpand canCollapse={false} onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByText("showing the 200 most recent of 250 bets · 10 of 200 shown")).toBeInTheDocument();
  });

  it("names the query when filtered", () => {
    render(<RevealFooter base="showing 200 of 250 bets" shown={6} matching={6} query="arsenal" isFiltered canExpand={false} canCollapse={false} onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByText(/· matching "arsenal"/)).toBeInTheDocument();
  });

  it("disables the expand controls when everything is shown but keeps Collapse usable", () => {
    render(<RevealFooter base="b" shown={35} matching={35} isFiltered={false} canExpand={false} canCollapse onExpand={() => {}} onExpandAll={() => {}} onCollapse={() => {}} />);
    expect(screen.getByRole("button", { name: /Expand/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Show all/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Collapse" })).toBeEnabled();
  });
});
