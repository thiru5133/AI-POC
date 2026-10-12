import type { McpServer, McpTestResult, McpTransport } from "../types";
import { apiFetch } from "./apiClient";

const BASE = "/api/org/mcp-servers";

export interface McpHeaderInput {
  name: string;
  /** Omit on a saved secret header to keep the saved value. */
  value?: string;
  secret: boolean;
}

export interface McpServerInput {
  name: string;
  url: string;
  /** On update this is the complete new list: headers left out are removed. */
  headers: McpHeaderInput[];
  transport: McpTransport;
  timeoutSeconds: number;
}

export const mcpService = {
  list: () => apiFetch<McpServer[]>(BASE),

  create: (input: McpServerInput) => apiFetch<McpServer>(BASE, { method: "POST", body: JSON.stringify(input) }),

  update: (id: string, changes: Partial<McpServerInput> & { enabled?: boolean }) =>
    apiFetch<McpServer>(`${BASE}/${id}`, { method: "PATCH", body: JSON.stringify(changes) }),

  remove: (id: string) => apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" }),

  test: (id: string) => apiFetch<McpTestResult>(`${BASE}/${id}/test`, { method: "POST" }),
};
