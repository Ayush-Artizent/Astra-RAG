export interface Credential {
  /** The value of the HTTP Authorization header. */
  header: string;
  /** Every string that could reveal the secret, so it can be scrubbed from errors. */
  secrets: string[];
}

const DEFAULT_USER = 'x-access-token';

/** `acme-prod` becomes `ASTRA_REPO_TOKEN_ACME_PROD`. */
export function credentialEnvName(ref: string): string {
  return `ASTRA_REPO_TOKEN_${ref.toUpperCase().replace(/[^A-Z0-9]/g, '_')}`;
}

/**
 * Finds the secret a `credentials_ref` names. MVP: an environment variable holding either a token, or
 * `user:token` for hosts that want a specific user name (GitLab uses `oauth2`). No ref means a public repo.
 */
export function resolveCredential(ref: string | null, env: NodeJS.ProcessEnv = process.env): Credential | null {
  if (ref === null) return null;
  const name = credentialEnvName(ref);
  const value = env[name];
  if (value === undefined || value.length === 0) {
    throw new Error(`The credentials "${ref}" are not configured on the adapter (set ${name})`);
  }
  const basic = value.includes(':') ? value : `${DEFAULT_USER}:${value}`;
  const encoded = Buffer.from(basic, 'utf8').toString('base64');
  const token = basic.slice(basic.indexOf(':') + 1);
  return { header: `Authorization: Basic ${encoded}`, secrets: [value, token, basic, encoded] };
}
