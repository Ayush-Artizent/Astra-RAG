const MAX_ERROR_LENGTH = 2000;

/**
 * Makes text safe to store in a job record and return to a caller: removes known secrets, credentials
 * embedded in URLs, and authorization headers, and cuts it to a sane length.
 */
export function scrubText(text: string, secrets: readonly string[] = []): string {
  let out = text;
  for (const secret of secrets) {
    // Very short values would blank out ordinary words.
    if (secret.length >= 4) out = out.split(secret).join('***');
  }
  out = out
    .replace(/(https?:\/\/)[^\s/@:]+(?::[^\s/@]*)?@/gi, '$1***@')
    .replace(/(authorization\s*[:=]\s*)(basic|bearer)?\s*[^\s"']+/gi, '$1***')
    .replace(/(x-access-token|oauth2|private-token)(:|=)\S+/gi, '$1$2***');
  return out.length > MAX_ERROR_LENGTH ? `${out.slice(0, MAX_ERROR_LENGTH)}...` : out;
}
