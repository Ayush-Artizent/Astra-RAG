import { loadConfig } from './config.js';
import { buildServer } from './server.js';

const config = loadConfig();
const app = buildServer(config);
app.listen({ port: config.port, host: config.host }).then((addr) => {
  console.log(`code adapter listening on ${addr}`);
});
