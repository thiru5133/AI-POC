import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";
import { session } from "../services/apiClient";
import { BusinessPicker } from "./BusinessPicker";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const business = (id: string, name: string, phone: string | null, isMarketplace = false) => ({
  id,
  name,
  phone,
  isMarketplace,
  domainName: "Hotels",
});

describe("BusinessPicker", () => {
  let fetchMock: MockInstance<typeof fetch>;
  beforeEach(() => {
    session.setToken("tok");
    session.setBusiness(null);
    fetchMock = vi.spyOn(globalThis, "fetch");
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the number of the selected business, and none when it has no number", async () => {
    fetchMock.mockResolvedValueOnce(
      json([business("a", "Alpha Hotel", "+914412345678"), business("b", "Beta Hotel", null), business("m", "All Hotels (compare)", "+17692630020", true)]),
    );
    render(<BusinessPicker>{(id) => <p>chatting with {id}</p>}</BusinessPicker>);
    // the first business the server lists is selected by default
    expect(await screen.findByRole("link", { name: "+914412345678" })).toHaveAttribute("href", "tel:+914412345678");

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Business"), "m");
    expect(screen.getByRole("link", { name: "+17692630020" })).toBeInTheDocument();
    expect(screen.getByText(/all hotels businesses/i)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Business"), "b");
    expect(screen.queryByText(/prefer to talk/i)).not.toBeInTheDocument();
    expect(screen.getByText("chatting with b")).toBeInTheDocument();
  });
});
