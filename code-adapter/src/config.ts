import './env.js';
import path from 'node:path';

export interface Config {
  port: number;
  host: string;
  dataDir: string;
  envelopeKey: string;
  maxEnvelopeLifetimeSeconds: number;
  clockSkewSeconds: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const envelopeKey = env.ASTRA_ENVELOPE_KEY;
  if (!envelopeKey || envelopeKey.length < 16) {
    throw new Error('ASTRA_ENVELOPE_KEY must be set to a secret of at least 16 characters');
  }
  return {
    port: Number(env.PORT ?? 8091),
    host: env.HOST ?? '127.0.0.1',
    dataDir: path.resolve(env.ASTRA_DATA_DIR ?? './data'),
    envelopeKey,
    maxEnvelopeLifetimeSeconds: 300,
    clockSkewSeconds: 30,
  };
}
