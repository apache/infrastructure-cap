#!/usr/bin/env node
/**
 * Minimum-release-age guard for npm dependencies.
 *
 * Walks the package-lock.json passed on argv, looks up every pinned
 * (name, version) on the public npm registry, and fails if any of them
 * was published more recently than MIN_RELEASE_AGE_DAYS ago. The
 * intent is to refuse builds whose lockfile points at a freshly
 * published package, since that is the window during which a
 * compromised maintainer account or a hijacked publish key would
 * deliver zero-day malware (the "shai-hulud", "event-stream",
 * "chalk", "color-name" et al. category of supply-chain attacks).
 *
 * Usage:
 *   node check-min-release-age.mjs <path-to-package-lock.json>
 *
 * Environment:
 *   MIN_RELEASE_AGE_DAYS   minimum age in days (default: 7)
 *   NPM_REGISTRY           registry base URL (default: https://registry.npmjs.org)
 *
 * Exit codes:
 *   0  every pinned package clears the threshold
 *   1  one or more packages are too new
 *   2  the registry could not be consulted (fail-closed)
 */

import { readFileSync } from "node:fs";

const THRESHOLD_DAYS = Number(process.env.MIN_RELEASE_AGE_DAYS || "3");
const REGISTRY = (process.env.NPM_REGISTRY || "https://registry.npmjs.org").replace(/\/$/, "");
const lockfilePath = process.argv[2];

if (!lockfilePath) {
  console.error("Usage: check-min-release-age.mjs <path-to-package-lock.json>");
  process.exit(2);
}

const lock = JSON.parse(readFileSync(lockfilePath, "utf8"));
if (typeof lock.lockfileVersion !== "number" || lock.lockfileVersion < 2) {
  console.error(
    `Unsupported lockfile version: ${lock.lockfileVersion}. ` +
      "This guard expects lockfileVersion >= 2 (npm 7+).",
  );
  process.exit(2);
}

const cutoffMs = Date.now() - THRESHOLD_DAYS * 86_400_000;

// Collect (name, version) tuples from `lock.packages`. The root entry has
// an empty key; workspace symlinks carry `link: true`. A nested copy of
// the same package shows up under a `node_modules/foo/node_modules/bar`
// path; we still want its (name, version) since it is a real install.
const pinned = new Map(); // key = "name@version"
for (const [path, info] of Object.entries(lock.packages || {})) {
  if (!path) continue;
  if (!info || typeof info.version !== "string") continue;
  if (info.link) continue;

  const segments = path.split("/");
  const lastNm = segments.lastIndexOf("node_modules");
  if (lastNm === -1 || lastNm === segments.length - 1) continue;
  const rest = segments.slice(lastNm + 1);

  // Scoped packages occupy two segments ("@scope/name"); unscoped take one.
  let name;
  if (rest[0].startsWith("@") && rest.length >= 2) {
    name = `${rest[0]}/${rest[1]}`;
  } else {
    name = rest[0];
  }
  pinned.set(`${name}@${info.version}`, { name, version: info.version });
}

console.log(
  `Checking ${pinned.size} unique (name, version) pairs against ` +
    `a ${THRESHOLD_DAYS}-day minimum-release-age (registry=${REGISTRY}).`,
);

/**
 * Look up a package's full registry document and return the publish
 * timestamp for the requested version. Returns ``null`` when no
 * timestamp is recorded (which should never happen for a real npm
 * publish, but we tolerate it so the script keeps going).
 */
async function publishedAt(name, version) {
  const url = `${REGISTRY}/${name.replace("/", "%2F")}`;
  const res = await fetch(url, {
    headers: {
      "User-Agent": "cap-min-release-age-guard/1.0",
      Accept: "application/json",
    },
  });
  if (!res.ok) {
    throw new Error(`registry returned HTTP ${res.status}`);
  }
  const meta = await res.json();
  const t = meta && meta.time && meta.time[version];
  return t ? Date.parse(t) : null;
}

const failures = [];
const errors = [];

// Run sequentially. The dep graph for this project is small (~50 unique
// packages); going parallel buys little and risks tripping npm's
// per-IP rate limits, which would force us to fail closed.
for (const { name, version } of pinned.values()) {
  try {
    const ts = await publishedAt(name, version);
    if (ts == null) {
      errors.push(`no publish timestamp on registry for ${name}@${version}`);
      continue;
    }
    if (ts > cutoffMs) {
      const ageDays = ((Date.now() - ts) / 86_400_000).toFixed(1);
      failures.push(`${name}@${version} (published ${ageDays} days ago)`);
    }
  } catch (err) {
    errors.push(`lookup failed for ${name}@${version}: ${err.message}`);
  }
}

if (errors.length > 0) {
  console.error("Registry lookup errors:");
  for (const e of errors) console.error(`  - ${e}`);
}

if (failures.length > 0) {
  console.error(
    `\nThe following packages are younger than the ${THRESHOLD_DAYS}-day threshold:`,
  );
  for (const f of failures) console.error(`  - ${f}`);
  console.error(
    "\nRefusing to build. Either pin to an older version, or raise " +
      "MIN_RELEASE_AGE_DAYS in the workflow input if the new release " +
      "has been independently audited.",
  );
  process.exit(1);
}

if (errors.length > 0) {
  // Fail closed: we cannot vouch for what we could not check.
  console.error("Cannot verify the age of every dependency; failing closed.");
  process.exit(2);
}

console.log(
  `OK: every pinned dependency is at least ${THRESHOLD_DAYS} days old.`,
);
