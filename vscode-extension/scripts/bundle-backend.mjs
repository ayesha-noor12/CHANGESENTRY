// Copy the Python backend (app/ and requirements.txt) into the extension so the .vsix is self-contained.
import { cpSync, existsSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "..", "backend");
const target = join(root, "backend");

if (!existsSync(join(source, "app", "cli.py"))) {
  console.error(`backend not found at ${source}`);
  process.exit(1);
}
rmSync(target, { recursive: true, force: true });
cpSync(join(source, "app"), join(target, "app"), {
  recursive: true,
  filter: (path) => !path.includes("__pycache__"),
});
cpSync(join(source, "requirements.txt"), join(target, "requirements.txt"));
console.log(`bundled backend into ${target}`);
