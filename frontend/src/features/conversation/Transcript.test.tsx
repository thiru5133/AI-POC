import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Transcript } from "./Transcript";

describe("Transcript", () => {
  it("shows an empty hint", () => {
    render(<Transcript entries={[]} />);
    expect(screen.getByText(/Start call/)).toBeInTheDocument();
  });

  it("renders user and assistant turns with partials marked", () => {
    render(
      <Transcript
        entries={[
          { id: "1", role: "assistant", text: "Welcome" },
          { id: "2", role: "user", text: "check in", partial: true },
        ]}
      />,
    );
    expect(screen.getByText("Welcome")).toBeInTheDocument();
    expect(screen.getByText("check in").closest("li")).toHaveClass("partial", "user");
  });
});
