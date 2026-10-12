import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { session } from "../services/apiClient";
import { LoginPage } from "./LoginPage";
import { VerifyOtpPage } from "./VerifyOtpPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function mount() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/verify" element={<VerifyOtpPage />} />
          <Route path="/chat" element={<h1>Chat page</h1>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("first-login verification", () => {
  beforeEach(() => session.setToken(null));
  afterEach(() => vi.restoreAllMocks());

  it("asks for the emailed code after a first login, then continues to the site", async () => {
    const user = { id: "u1", name: "Asha", email: "a@x.com", role: "user", status: "active", tenantId: null };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/auth/refresh") return json({}, 401);
      if (url === "/api/auth/login") return json({ accessToken: null, user: null, otpRequired: true, email: "a@x.com" });
      if (url === "/api/auth/verify-otp") return json({ accessToken: "tok", user, otpRequired: false, email: null });
      return json({}, 404);
    });
    mount();

    await userEvent.type(await screen.findByLabelText("Email"), "a@x.com");
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("heading", { name: "Verify your email" })).toBeInTheDocument();
    expect(session.getToken()).toBeNull(); // no session before the code is entered

    await userEvent.type(screen.getByLabelText("Verification code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify and continue" }));

    expect(await screen.findByRole("heading", { name: "Chat page" })).toBeInTheDocument();
    const verifyCall = fetchMock.mock.calls.find(([u]) => String(u) === "/api/auth/verify-otp");
    expect(JSON.parse(String(verifyCall?.[1]?.body))).toEqual({ email: "a@x.com", code: "123456" });
    expect(session.getToken()).toBe("tok");
  });

  it("shows the server's message for a wrong code", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/auth/refresh") return json({}, 401);
      if (url === "/api/auth/login") return json({ accessToken: null, user: null, otpRequired: true, email: "a@x.com" });
      return json({ error: { code: "unauthorized", message: "That code is not valid or has expired", requestId: "r" } }, 401);
    });
    mount();
    await userEvent.type(await screen.findByLabelText("Email"), "a@x.com");
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass-1");
    await userEvent.click(screen.getByRole("button", { name: "Log in" }));
    await userEvent.type(await screen.findByLabelText("Verification code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("not valid or has expired");
  });
});
