import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
    // Several tests build real CodeGraph indexes, which takes 2 to 4 seconds alone and longer when test
    // files run in parallel. The default 5 seconds made them fail under load.
    testTimeout: 30_000,
    hookTimeout: 180_000,
  },
});
