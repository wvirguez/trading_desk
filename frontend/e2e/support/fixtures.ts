import { readFileSync } from "node:fs";
import { join } from "node:path";

const FIXTURES_DIR = join(process.cwd(), "e2e", "fixtures");

export function loadFixture<T>(name: string): T {
  const raw = readFileSync(join(FIXTURES_DIR, name), "utf8");
  return JSON.parse(raw) as T;
}