import { spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const generatedFiles = ["next-env.d.ts", "tsconfig.json"];
const snapshots = new Map(
  await Promise.all(
    generatedFiles.map(async (relativePath) => [
      relativePath,
      await readFile(path.join(root, relativePath)),
    ]),
  ),
);

const configuredPort = process.env.MARKLENS_E2E_PORT ?? "3107";
if (!/^\d{2,5}$/.test(configuredPort)) {
  throw new Error("MARKLENS_E2E_PORT must be a valid TCP port");
}
const port = Number(configuredPort);
if (port < 1024 || port > 65_535) {
  throw new Error("MARKLENS_E2E_PORT must be between 1024 and 65535");
}
const baseURL = `http://127.0.0.1:${port}`;

function waitForExit(child) {
  if (child.exitCode !== null) return Promise.resolve(child.exitCode);
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve(code ?? 1));
  });
}

let server = null;
let serverOutput = "";

async function startWindowsServer() {
  try {
    await fetch(baseURL, { signal: AbortSignal.timeout(750) });
    throw new Error(`E2E port ${port} is already in use`);
  } catch (error) {
    if (error instanceof Error && error.message.includes("already in use")) {
      throw error;
    }
  }

  const nextCli = path.join(root, "node_modules", "next", "dist", "bin", "next");
  server = spawn(
    process.execPath,
    [nextCli, "dev", "--hostname", "127.0.0.1", "--port", String(port)],
    {
      cwd: root,
      env: {
        ...process.env,
        MARKLENS_TURNSTILE_DEV_BYPASS: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  for (const stream of [server.stdout, server.stderr]) {
    stream.on("data", (chunk) => {
      serverOutput = `${serverOutput}${chunk}`.slice(-20_000);
    });
  }

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(`E2E server exited early.\n${serverOutput}`);
    }
    try {
      const response = await fetch(baseURL, {
        signal: AbortSignal.timeout(1_000),
      });
      if (response.status < 500) return;
    } catch {
      // The dev server is still starting.
    }
    await delay(250);
  }
  throw new Error(`E2E server did not become ready.\n${serverOutput}`);
}

async function stopWindowsServer() {
  if (!server || server.exitCode !== null || !server.pid) return;
  const killer = spawn(
    "taskkill",
    ["/PID", String(server.pid), "/T", "/F"],
    { stdio: "ignore", windowsHide: true },
  );
  await waitForExit(killer);
}

const cli = path.join(root, "node_modules", "@playwright", "test", "cli.js");
let child = null;
let forwardedSignal = null;
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.once(signal, () => {
    forwardedSignal = signal;
    child?.kill(signal);
  });
}

let exitCode = 1;
let childError = null;
try {
  if (process.platform === "win32") await startWindowsServer();
  child = spawn(process.execPath, [cli, "test", ...process.argv.slice(2)], {
    cwd: root,
    env: {
      ...process.env,
      ...(server ? { MARKLENS_E2E_REUSE_SERVER: "1" } : {}),
    },
    stdio: "inherit",
  });
  exitCode = await waitForExit(child);
} catch (error) {
  childError = error;
} finally {
  try {
    await stopWindowsServer();
  } finally {
    await Promise.all(
      [...snapshots].map(([relativePath, contents]) =>
        writeFile(path.join(root, relativePath), contents),
      ),
    );
  }
}

if (childError) throw childError;

if (forwardedSignal) {
  process.kill(process.pid, forwardedSignal);
} else {
  process.exit(exitCode);
}
