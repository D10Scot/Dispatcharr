import { startServer } from './server.js';

const port = Number(process.env.UPSTREAM_PORT ?? 8080);

startServer(port).then((server) => {
  console.log(`e2e-upstream listening on ${server.port}`);
});
