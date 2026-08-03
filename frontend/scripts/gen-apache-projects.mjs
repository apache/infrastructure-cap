#!/usr/bin/env node
// Regenerate src/lib/apache-projects.json: a compact { id: "Apache Name" }
// map of every ASF top-level project, used to render canonical project
// names (e.g. "jmeter" -> "Apache JMeter") in the new-question form.
//
// The casing of names like JMeter / CloudStack / CouchDB cannot be
// recovered from the lowercase project id alone, so we bundle the
// authoritative names published by projects.apache.org. Re-run whenever
// the project list changes:
//
//     node scripts/gen-apache-projects.mjs
//
// At runtime, src/lib/projects.ts falls back to a live fetch of the same
// feed for any id missing from this bundle, then to a capitalize
// heuristic, so a stale bundle degrades gracefully.

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const FEED = "https://projects.apache.org/json/foundation/projects.json";
const OUT = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "lib",
  "apache-projects.json",
);

const res = await fetch(FEED);
if (!res.ok) {
  console.error(`Failed to fetch ${FEED}: HTTP ${res.status}`);
  process.exit(1);
}
const data = await res.json();

const map = {};
for (const [id, value] of Object.entries(data)) {
  if (value && typeof value.name === "string") map[id] = value.name;
}

const sorted = Object.fromEntries(
  Object.keys(map)
    .sort()
    .map((id) => [id, map[id]]),
);

writeFileSync(OUT, JSON.stringify(sorted, null, 1) + "\n");
console.log(`Wrote ${Object.keys(sorted).length} projects to ${OUT}`);
