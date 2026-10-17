import axios from "axios";

/**
 * Base URL for the Clinical EDC API.
 *
 * Defaults to the relative `/api/v1`, which is served same-origin in
 * production and proxied to the backend by Vite in development. Override with
 * the `VITE_API_BASE_URL` environment variable to point the frontend at a
 * different backend (for example an absolute `https://api.example.com/api/v1`).
 */
export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

/**
 * Configured Axios instance for the Clinical EDC API.
 * All requests target the versioned API (see {@link API_BASE_URL}).
 * Auth tokens are injected via request interceptor.
 * 401 responses trigger token refresh or logout.
 */
export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

interface RefreshTokenResponse {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
}

let refreshPromise: Promise<string> | null = null;

// Attach access token to every outgoing request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token")?.trim();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function getRefreshEndpoint(): string {
  return localStorage.getItem("auth_provider") === "cognito"
    ? `${API_BASE_URL}/auth/cognito/refresh`
    : `${API_BASE_URL}/auth/refresh`;
}

function isAuthenticationRequest(url?: string): boolean {
  const path = url?.split("?", 1)[0] ?? "";
  return [
    "/auth/login",
    "/auth/refresh",
    "/auth/cognito/refresh",
    "/auth/cognito/exchange",
  ].some((endpoint) => path.endsWith(endpoint));
}

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem("refresh_token")?.trim();
  if (!refreshToken) {
    throw new Error("No refresh token");
  }

  const endpoint = getRefreshEndpoint();
  const { data } = await axios.post<RefreshTokenResponse>(endpoint, {
    refresh_token: refreshToken,
  });

  // For Cognito, the ID token is the Bearer credential (it carries the
  // verified email/name claims the backend needs); fall back to the access
  // token for the local provider.
  const isCognito = localStorage.getItem("auth_provider") === "cognito";
  const nextToken = isCognito && data.id_token ? data.id_token : data.access_token;
  if (!nextToken) {
    throw new Error("Refresh response did not include an access token");
  }

  localStorage.setItem("access_token", nextToken);
  if (data.refresh_token) {
    localStorage.setItem("refresh_token", data.refresh_token);
  }
  return nextToken;
}

function clearAuthenticationSession(): void {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("auth_provider");
}

// Handle 401 responses globally — attempt token refresh or redirect to login
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (
      error.response?.status === 401 &&
      originalRequest &&
      !originalRequest._retry &&
      !isAuthenticationRequest(originalRequest.url)
    ) {
      originalRequest._retry = true;

      try {
        const currentToken = localStorage.getItem("access_token")?.trim();
        const sentAuthorization = originalRequest.headers?.Authorization;
        if (currentToken && sentAuthorization !== `Bearer ${currentToken}`) {
          originalRequest.headers.Authorization = `Bearer ${currentToken}`;
          return api(originalRequest);
        }

        // A page can issue several API calls at once. Reuse one in-flight
        // refresh so a second 401 cannot invalidate newly rotated credentials.
        const pendingRefresh = refreshPromise ??= refreshAccessToken();
        let nextToken: string;
        try {
          nextToken = await pendingRefresh;
        } finally {
          if (refreshPromise === pendingRefresh) {
            refreshPromise = null;
          }
        }
        originalRequest.headers.Authorization = `Bearer ${nextToken}`;
        return api(originalRequest);
      } catch {
        // Refresh failed — clear tokens and redirect to login
        clearAuthenticationSession();
        if (window.location.pathname !== "/login") {
          window.location.assign("/login");
        }
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  },
);

/**
 * Standard paginated response envelope from the API.
 */
export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

/**
 * Standard error envelope from the API.
 */
export interface ApiError {
  detail?: string;
  error?: {
    code?: string;
    message?: string;
    details?: Record<string, unknown>;
    request_id?: string;
    correlation_id?: string;
  };
  request_id?: string;
  errors?: Record<string, string[]>;
}

/** Return a sanitized API message from either supported error envelope. */
export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!axios.isAxiosError<ApiError>(error)) {
    return fallback;
  }
  return error.response?.data?.error?.message ?? error.response?.data?.detail ?? fallback;
}
