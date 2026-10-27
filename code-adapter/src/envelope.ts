import { createHmac, timingSafeEqual } from 'node:crypto';
import { unauthorized, ProblemError } from './errors.js';

export interface Envelope {
  org_id: string;
  project_id: string;
  scopes: string[];
  request_id: string;
  iat: number;
  exp: number;
}

export interface EnvelopeLimits {
  key: string;
  maxLifetimeSeconds: number;
  clockSkewSeconds: number;
}

/** Ids end up in directory names, so they are restricted here as well as in paths.ts. */
export const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

const b64u = (buf: Buffer) => buf.toString('base64url');

/**
 * Wire format: `<base64url(JSON payload)>.<base64url(HMAC-SHA256(payload part, key))>`.
 * The format is a proposal for review; the gateway must mint the same shape.
 */
export function signEnvelope(payload: Envelope, key: string): string {
  const body = b64u(Buffer.from(JSON.stringify(payload), 'utf8'));
  const sig = b64u(createHmac('sha256', key).update(body).digest());
  return `${body}.${sig}`;
}

export function verifyEnvelope(
  header: string | undefined,
  limits: EnvelopeLimits,
  nowSeconds: number = Math.floor(Date.now() / 1000),
): Envelope {
  if (!header) throw unauthorized('envelope_invalid', 'Missing X-Astra-Envelope header');
  const parts = header.split('.');
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    throw unauthorized('envelope_invalid', 'Malformed envelope');
  }
  const [body, sig] = parts as [string, string];

  const expected = createHmac('sha256', limits.key).update(body).digest();
  const given = Buffer.from(sig, 'base64url');
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) {
    throw unauthorized('envelope_invalid', 'Bad envelope signature');
  }

  let payload: Partial<Envelope>;
  try {
    payload = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
  } catch {
    throw unauthorized('envelope_invalid', 'Malformed envelope payload');
  }

  const { org_id, project_id, scopes, request_id, iat, exp } = payload;
  if (
    typeof org_id !== 'string' || !ID_PATTERN.test(org_id) ||
    typeof project_id !== 'string' || !ID_PATTERN.test(project_id) ||
    !Array.isArray(scopes) || !scopes.every((s) => typeof s === 'string') ||
    typeof request_id !== 'string' ||
    !Number.isInteger(iat) || !Number.isInteger(exp)
  ) {
    throw unauthorized('envelope_invalid', 'Envelope fields are missing or invalid');
  }
  const issued = iat as number;
  const expires = exp as number;

  if (expires - issued > limits.maxLifetimeSeconds) {
    throw unauthorized('envelope_lifetime_exceeded', 'Envelope lifetime is over the 5 minute maximum');
  }
  if (nowSeconds > expires + limits.clockSkewSeconds) {
    throw unauthorized('envelope_expired', 'Envelope has expired');
  }
  if (issued > nowSeconds + limits.clockSkewSeconds) {
    throw unauthorized('envelope_invalid', 'Envelope issued in the future');
  }

  return { org_id, project_id, scopes, request_id, iat: issued, exp: expires };
}

export function requireScope(envelope: Envelope, scope: string): void {
  if (!envelope.scopes.includes(scope)) {
    throw new ProblemError(403, 'scope_missing', 'Forbidden', `Missing scope ${scope}`);
  }
}
