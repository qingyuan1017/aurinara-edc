import type { AxiosError, AxiosRequestConfig } from "axios";

import { api } from "@/lib/api";

/**
 * Custom Axios instance for Orval-generated API clients.
 *
 * Every generated hook and request function routes through this function,
 * which delegates to the shared {@link api} instance in `src/lib/api.ts`. That
 * means generated calls automatically inherit:
 *   - the configurable base URL (`VITE_API_BASE_URL`, default `/api/v1`);
 *   - the Bearer-token request interceptor;
 *   - the 401 refresh-and-retry / logout response interceptor.
 *
 * A cancellation signal is wired up so TanStack Query can abort in-flight
 * requests (e.g. on unmount or query-key change). Orval detects the attached
 * `.cancel()` method and calls it when appropriate.
 */
export const customInstance = <T>(
  config: AxiosRequestConfig,
  options?: AxiosRequestConfig,
): Promise<T> => {
  const controller = new AbortController();

  const promise = api({
    ...config,
    ...options,
    signal: config.signal ?? options?.signal ?? controller.signal,
  }).then(({ data }) => data as T);

  // Allow TanStack Query / Orval to cancel the request.
  (promise as Promise<T> & { cancel?: () => void }).cancel = () => {
    controller.abort();
  };

  return promise;
};

export default customInstance;

/**
 * Error type surfaced by generated hooks. Mirrors the API's error envelope.
 */
export type ErrorType<Error> = AxiosError<Error>;

/**
 * Body type helper used by some Orval configurations.
 */
export type BodyType<BodyData> = BodyData;
