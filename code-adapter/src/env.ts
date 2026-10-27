// Imported for its side effect, before anything that loads CodeGraph.
//
// CodeGraph reports anonymous usage stats unless told not to. This service handles customer code,
// so telemetry is off for this process and for every child process that inherits the environment.
process.env.CODEGRAPH_TELEMETRY = '0';
