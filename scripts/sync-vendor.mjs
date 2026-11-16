#!/usr/bin/env node
// Copies the browser libraries listed in vendor/assets.json from
// vendor/node_modules/ into app/static/vendor/ and writes
// app/static/vendor/manifest.json (installed versions + SRI hashes).
//
// Run after `npm ci` in vendor/ (scripts/vendor-assets.sh does both).
// The result is committed to git, so the server never needs npm or internet.
// Node 18+ and no dependencies.

import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const VENDOR_SRC = path.join(ROOT, "vendor");
const MODULES = path.join(VENDOR_SRC, "node_modules");
const OUT = path.join(ROOT, "app", "static", "vendor");

// Never copied when a whole package folder is vendored
const DIR_EXCLUDE = [
  /^package\.json$/, /^README(\.md)?$/i, /^CHANGELOG(\.md)?$/i, /^bower\.json$/,
  /^composer\.json$/, /\.d\.ts$/, /\.map$/, /^node_modules$/,
];

const assets = JSON.parse(fs.readFileSync(path.join(VENDOR_SRC, "assets.json"), "utf8")).assets;
const declared = JSON.parse(fs.readFileSync(path.join(VENDOR_SRC, "package.json"), "utf8")).dependencies;

const errors = [];
const files = {};      // local path -> sha384 SRI
const packages = {};   // package -> installed version

const sri = (buf) => "sha384-" + createHash("sha384").update(buf).digest("base64");

function installedVersion(pkg) {
  if (packages[pkg]) return packages[pkg];
  const pj = path.join(MODULES, pkg, "package.json");
  if (!fs.existsSync(pj)) {
    errors.push(`package ${pkg} is not installed (run npm ci in vendor/)`);
    return null;
  }
  const v = JSON.parse(fs.readFileSync(pj, "utf8")).version;
  if (declared[pkg] && declared[pkg] !== v) {
    errors.push(`package ${pkg}: package.json wants ${declared[pkg]}, node_modules has ${v}`);
  }
  packages[pkg] = v;
  return v;
}

function put(local, buf) {
  const dest = path.join(OUT, local);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, buf);
  files[local] = sri(buf);
}

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (DIR_EXCLUDE.some((re) => re.test(e.name))) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (e.isFile()) out.push(p);
  }
  return out;
}

// Keep the downloaded (non-npm) files: they are only fetched when missing.
const kept = {};
for (const a of assets) {
  const p = path.join(OUT, a.local);
  if (a.url && fs.existsSync(p)) kept[a.local] = fs.readFileSync(p);
}

// Start from an empty folder so files from old versions do not linger.
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

for (const a of assets) {
  if (a.url) {
    let buf = kept[a.local];
    if (!buf) {
      try {
        const res = await fetch(a.url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        buf = Buffer.from(await res.arrayBuffer());
      } catch (e) {
        errors.push(`${a.local}: download of ${a.url} failed (${e.message})`);
        continue;
      }
    }
    put(a.local, buf);
    continue;
  }

  if (!installedVersion(a.package)) continue;
  const pkgDir = path.join(MODULES, a.package);

  if (a.file) {
    const src = path.join(pkgDir, a.file);
    if (!fs.existsSync(src)) {
      errors.push(`${a.local}: ${a.package} has no file ${a.file}`);
      continue;
    }
    put(a.local, fs.readFileSync(src));
    continue;
  }

  const srcDir = path.join(pkgDir, a.dir);
  if (!fs.existsSync(srcDir)) {
    errors.push(`${a.local}: ${a.package} has no folder ${a.dir}`);
    continue;
  }
  for (const src of walk(srcDir)) {
    if (a.min_only && /\.(js|css)$/.test(src) && !/\.min\.(js|css)$/.test(src)) {
      const twin = src.replace(/\.(js|css)$/, ".min.$1");
      if (fs.existsSync(twin)) continue;
    }
    const rel = path.relative(srcDir, src).split(path.sep).join("/");
    if (a.match && !new RegExp(a.match).test(rel)) continue;
    put(a.local + rel, fs.readFileSync(src));
  }
}

const sorted = (o) => Object.fromEntries(Object.keys(o).sort().map((k) => [k, o[k]]));
fs.writeFileSync(
  path.join(OUT, "manifest.json"),
  JSON.stringify({ packages: sorted(packages), files: sorted(files) }, null, 1) + "\n",
);

if (errors.length) {
  console.error("Vendor sync FAILED:\n  " + errors.join("\n  "));
  process.exit(1);
}
console.log(`Vendor sync OK: ${Object.keys(packages).length} packages, ${Object.keys(files).length} files in app/static/vendor/`);
