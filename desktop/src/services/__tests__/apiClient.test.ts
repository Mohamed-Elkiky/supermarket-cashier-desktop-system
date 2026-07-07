import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  api,
  ApiError,
  login,
  isAuthenticated,
  __setTokensForTest,
} from "../apiClient";

type MockResponse = { status: number; body: unknown };

function res({ status, body }: MockResponse) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function mockFetch(...responses: MockResponse[]) {
  const fn = vi.fn();
  responses.forEach((r) => fn.mockResolvedValueOnce(res(r)));
  globalThis.fetch = fn as unknown as typeof fetch;
  return fn;
}

beforeEach(() => {
  __setTokensForTest(null);
});

describe("apiClient envelope handling", () => {
  it("unwraps .data on success", async () => {
    __setTokensForTest({ access: "a", refresh: "r", email: "x", role: "cashier" });
    mockFetch({ status: 200, body: { success: true, data: [{ id: 1, name: "Grocery" }] } });
    const departments = await api.getDepartments();
    expect(departments).toEqual([{ id: 1, name: "Grocery" }]);
  });

  it("throws a typed ApiError on failure", async () => {
    __setTokensForTest({ access: "a", refresh: "r", email: "x", role: "cashier" });
    mockFetch({
      status: 400,
      body: { success: false, error: { code: "validation_error", status: 400, errors: ["bad"] } },
    });
    await expect(api.getDepartments()).rejects.toMatchObject({
      name: "ApiError",
      code: "validation_error",
      status: 400,
      errors: ["bad"],
    });
  });
});

describe("login", () => {
  it("stores tokens and marks authenticated", async () => {
    mockFetch({
      status: 200,
      body: { success: true, data: { access: "acc", refresh: "ref", email: "a@b.c", role: "cashier" } },
    });
    const auth = await login("a@b.c", "pw");
    expect(auth.access).toBe("acc");
    expect(isAuthenticated()).toBe(true);
  });
});

describe("401 -> refresh -> retry", () => {
  it("refreshes the token once and retries the original request", async () => {
    __setTokensForTest({ access: "old", refresh: "ref", email: "x", role: "cashier" });
    const fetchMock = mockFetch(
      { status: 401, body: { success: false, error: { code: "token_expired", status: 401, errors: [] } } },
      { status: 200, body: { success: true, data: { access: "new" } } }, // refresh
      { status: 200, body: { success: true, data: [{ id: 9, name: "Deli" }] } }, // retry
    );

    const result = await api.getDepartments();
    expect(result).toEqual([{ id: 9, name: "Deli" }]);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // The retried request must carry the refreshed access token.
    const retryInit = fetchMock.mock.calls[2][1] as RequestInit;
    expect((retryInit.headers as Record<string, string>)["Authorization"]).toBe("Bearer new");
    // The middle call must hit the refresh endpoint.
    expect(String(fetchMock.mock.calls[1][0])).toContain("/auth/refresh/");
  });

  it("clears auth and throws when refresh fails", async () => {
    __setTokensForTest({ access: "old", refresh: "ref", email: "x", role: "cashier" });
    mockFetch(
      { status: 401, body: { success: false, error: { code: "token_expired", status: 401, errors: [] } } },
      { status: 401, body: { success: false, error: { code: "invalid_refresh", status: 401, errors: [] } } },
    );

    await expect(api.getDepartments()).rejects.toBeInstanceOf(ApiError);
    expect(isAuthenticated()).toBe(false);
  });
});
