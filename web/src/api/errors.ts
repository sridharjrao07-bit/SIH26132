// One error type for the whole app (G8). The backend always sends {"detail": ...},
// but detail can be a string OR a FastAPI validation array. 404 = "not found or not yours".
export type ApiErrorKind =
  | 'bad_request' | 'auth' | 'forbidden' | 'not_found' | 'conflict'
  | 'validation' | 'rate_limited' | 'unavailable' | 'server'
  | 'network' | 'timeout' | 'contract';

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  /** field path -> message, only for 422 array errors */
  readonly fields: Record<string, string>;
  constructor(status: number, kind: ApiErrorKind, message: string, fields: Record<string, string> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    this.fields = fields;
  }
  /** Worth retrying automatically (TanStack Query `retry`)? */
  get retryable(): boolean {
    return this.kind === 'network' || this.kind === 'timeout' || this.kind === 'unavailable' || this.kind === 'server';
  }
}

const KIND_BY_STATUS: Record<number, ApiErrorKind> = {
  400: 'bad_request', 401: 'auth', 403: 'forbidden', 404: 'not_found', 409: 'conflict',
  422: 'validation', 429: 'rate_limited', 503: 'unavailable',
};

type FastApiIssue = { loc?: (string | number)[]; msg?: string };

export function normalizeApiError(status: number, body: unknown): ApiError {
  const kind = KIND_BY_STATUS[status] ?? (status >= 500 ? 'server' : 'bad_request');
  const detail = (body as { detail?: unknown } | null)?.detail;

  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const issue of detail as FastApiIssue[]) {
      // drop the leading "body"/"query" segment: ["body","quantity_qtl"] -> "quantity_qtl"
      const path = (issue.loc ?? []).slice(1).join('.') || '_';
      fields[path] = issue.msg ?? 'invalid';
    }
    return new ApiError(status, kind, Object.values(fields)[0] ?? 'invalid input', fields);
  }
  if (typeof detail === 'string' && detail) return new ApiError(status, kind, detail);
  return new ApiError(status, kind, `request failed (${status})`);
}
