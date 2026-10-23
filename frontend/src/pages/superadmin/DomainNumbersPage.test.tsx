import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../../services/apiClient";
import { DomainNumbersPage } from "./DomainNumbersPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const domain = (id: string, name: string, number: string | null = null) => ({
  id,
  key: id,
  name,
  number,
  transferNumber: null,
});

describe("DomainNumbersPage", () => {
  let fetchMock: MockInstance<typeof fetch>;
  beforeEach(() => {
    session.setToken("tok");
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists every domain with its current number", async () => {
    fetchMock.mockResolvedValueOnce(json([domain("fitness", "Fitness", "+17372508034"), domain("hotel", "Hotels")]));
    render(<DomainNumbersPage />);
    expect(await screen.findByDisplayValue("+17372508034")).toBeInTheDocument();
    expect(screen.getByLabelText("Hotels number")).toHaveValue("");
  });

  it("saves one domain's number, sending an empty transfer number as null", async () => {
    fetchMock
      .mockResolvedValueOnce(json([domain("hotel", "Hotels")]))
      .mockResolvedValueOnce(json(domain("hotel", "Hotels", "+17692630020")));
    render(<DomainNumbersPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Hotels number"), "+17692630020");
    await user.click(within(screen.getByLabelText("Hotels number").closest("form")!).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(String(url)).toContain("/api/superadmin/domain-numbers/hotel");
    expect((init as RequestInit).method).toBe("PUT");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ number: "+17692630020", transferNumber: null });
  });

  it("shows why a number could not be saved", async () => {
    fetchMock
      .mockResolvedValueOnce(json([domain("hotel", "Hotels")]))
      .mockResolvedValueOnce(json({ error: { code: "number_taken", message: "That number is already used by another business or domain" } }, 409));
    render(<DomainNumbersPage />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Hotels number"), "+17692630020");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("already used by another business or domain"));
  });
});
