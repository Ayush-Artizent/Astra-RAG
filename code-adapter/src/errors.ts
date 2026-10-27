export type ErrorCode =
  | 'no_search_terms'
  | 'flow_needs_two_symbols'
  | 'callers_needs_one_symbol'
  | 'impact_needs_one_symbol'
  | 'invalid_field'
  | 'envelope_invalid'
  | 'envelope_expired'
  | 'envelope_lifetime_exceeded'
  | 'scope_missing'
  | 'project_unknown'
  | 'path_refused'
  | 'job_conflict'
  | 'rate_limited'
  | 'dependency_unavailable';

/** An error that maps to an RFC 9457 problem+json response. */
export class ProblemError extends Error {
  constructor(
    readonly status: number,
    readonly errorCode: ErrorCode,
    readonly title: string,
    detail?: string,
    readonly field?: string,
  ) {
    super(detail ?? title);
  }
}

export const unauthorized = (code: ErrorCode, detail: string) =>
  new ProblemError(401, code, 'Unauthorized', detail);
