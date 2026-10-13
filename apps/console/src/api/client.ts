import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

// Contract types come from the backend's OpenAPI document (npm run gen:api).
export type Schema = components['schemas']
export type User = Schema['UserOut']
export type WorkflowDefinition = Schema['WorkflowDefinition']
export type NodeDef = Schema['NodeDef']
export type EdgeDef = Schema['EdgeDef']
export type CatalogNode = Schema['CatalogNode']
export type CatalogParam = Schema['CatalogParam']
export type ValidationIssue = Schema['ValidationIssue']
export type RunDetail = Schema['RunDetail']
export type RunSummary = Schema['RunSummary']
export type NodeRun = Schema['NodeRunOut']
export type RunEvent = Schema['RunEventOut']
export type Approval = Schema['ApprovalOut']
export type WorkflowDetail = Schema['WorkflowDetail']

const TOKEN_KEY = 'hacfew.token'

// sessionStorage keeps the bearer token out of long-lived storage; it is cleared with the tab.
export const tokenStore = {
  get: (): string | null => {
    try { return sessionStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t) } catch { /* storage unavailable */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* storage unavailable */ } },
}

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

const authMiddleware: Middleware = {
  onRequest({ request }) {
    const t = tokenStore.get()
    if (t) request.headers.set('Authorization', `Bearer ${t}`)
    return request
  },
  onResponse({ response, request }) {
    if (response.status === 401 && !request.url.includes('/auth/login')) onUnauthorized()
    return response
  },
}

// The OpenAPI paths carry the /api/v1 prefix; strip it so call sites read naturally.
type Strip<P> = { [K in keyof P as K extends `/api/v1${infer R}` ? R : K]: P[K] }
export const api = createClient<Strip<paths>>({ baseUrl: '/api/v1' })
api.use(authMiddleware)

export class ApiError extends Error {
  status: number
  issues?: ValidationIssue[]
  constructor(status: number, message: string, issues?: ValidationIssue[]) {
    super(message)
    this.status = status
    this.issues = issues
  }
}

/** FastAPI errors are `{detail: string}` or `{detail: {message, issues}}` or a 422 validation array. */
export function toApiError(status: number, body: unknown): ApiError {
  const detail = (body as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return new ApiError(status, detail)
  if (Array.isArray(detail)) {
    const msg = detail.map((d: { loc?: string[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('; ')
    return new ApiError(status, msg || 'Invalid request')
  }
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; issues?: ValidationIssue[] }
    return new ApiError(status, d.message ?? 'Request failed', d.issues)
  }
  return new ApiError(status, status >= 500 ? 'The server had a problem. Try again.' : 'Request failed')
}

/** Unwraps an openapi-fetch result, throwing a typed ApiError so react-query can surface it. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let res
  try { res = await p } catch { throw new ApiError(0, 'Cannot reach the API. Is the backend running?') }
  if (res.error !== undefined || res.data === undefined) {
    if (res.response.status === 204) return undefined as T
    throw toApiError(res.response.status, res.error)
  }
  return res.data
}
