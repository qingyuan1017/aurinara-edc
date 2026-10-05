import axios from 'axios'

/**
 * Configured Axios instance for the Clinical EDC API.
 * All requests target the versioned API at /api/v1.
 * Auth tokens are injected via request interceptor.
 * 401 responses trigger token refresh or logout.
 */
export const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
})

// Attach access token to every outgoing request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export function getRefreshEndpoint(): string {
  return localStorage.getItem('auth_provider') === 'cognito'
    ? '/api/v1/auth/cognito/refresh'
    : '/api/v1/auth/refresh'
}

// Handle 401 responses globally — attempt token refresh or redirect to login
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        const refreshToken = localStorage.getItem('refresh_token')
        if (!refreshToken) {
          throw new Error('No refresh token')
        }

        const endpoint = getRefreshEndpoint()
        const { data } = await axios.post(endpoint, {
          refresh_token: refreshToken,
        })

        localStorage.setItem('access_token', data.access_token)
        if (data.refresh_token) {
          localStorage.setItem('refresh_token', data.refresh_token)
        }
        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return api(originalRequest)
      } catch {
        // Refresh failed — clear tokens and redirect to login
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('auth_provider')
        window.location.href = '/login'
        return Promise.reject(error)
      }
    }

    return Promise.reject(error)
  },
)

/**
 * Standard paginated response envelope from the API.
 */
export interface PaginatedResponse<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

/**
 * Standard error envelope from the API.
 */
export interface ApiError {
  detail: string
  request_id?: string
  errors?: Record<string, string[]>
}
