#!/usr/bin/env node
// npm audit for a folder whose packages are only used as files copied into
// the app (vendor/): only vulnerabilities in the direct dependencies matter,
// because nothing else is shipped or run. Transitive ones (build tools some
// packages wrongly list as dependencies) are printed but do not fail.
// Usage: node scripts/npm-audit-direct.mjs vendor
import { execSync } from "node:child_process";

const dir = process.argv[2] || "vendor";
let out;
try {
  out = execSync("npm audit --json", { cwd: dir, encoding: "utf8", maxBuffer: 64 << 20 });
} catch (e) {
  out = e.stdout; // npm audit exits 1 when it finds anything
}
const vulns = Object.values(JSON.parse(out).vulnerabilities || {});
const direct = vulns.filter((v) => v.isDirect);
const indirect = vulns.filter((v) => !v.isDirect);
for (const v of direct) {
  const titles = v.via.filter((x) => typeof x === "object").map((x) => `${x.title} (${x.url})`);
  console.log(`DIRECT  ${v.name} ${v.range} [${v.severity}]\n    ${titles.join("\n    ")}`);
}
if (indirect.length) {
  console.log(`\nNot shipped (transitive, ignored): ${indirect.map((v) => `${v.name} [${v.severity}]`).join(", ")}`);
}
if (direct.length) process.exit(1);
console.log(`\n${dir}: no known vulnerabilities in the shipped packages`);
