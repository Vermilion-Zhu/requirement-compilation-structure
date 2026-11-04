import { createApp } from "./app.js";
import { createDatabaseClient } from "./db/client.js";
import { initializeDatabase } from "./db/initialize.js";

const port = Number(process.env.PORT ?? "3000");
if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error("Invalid PORT");
// The ARC-Bench runner starts the application and reaches it from outside the
// container, so bind every interface unless the runner supplies a narrower HOST.
const host = process.env.HOST?.trim() || "0.0.0.0";
const connection = createDatabaseClient();
initializeDatabase(connection);
const server = createApp(connection).listen(port, host, (error?: Error) => {
  if (error) {
    connection.close();
    console.error(error);
    process.exitCode = 1;
    return;
  }
  const address = server.address();
  const actual = typeof address === "object" && address ? `${address.address}:${address.port}` : `${host}:${port}`;
  console.log(`Application listening at http://${actual}`);
});
for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => server.close(() => { connection.close(); process.exit(0); }));
}
