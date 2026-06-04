import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const rootDir = resolve(new URL("..", import.meta.url).pathname);
const backendPath = resolve(rootDir, "backend/app/services/application_fill_review.py");
const frontendPath = resolve(rootDir, "frontend/src/lib/supportedAts.ts");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function quotedValues(source) {
  return [...source.matchAll(/["']([a-z0-9_]+)["']/g)].map((match) => match[1]);
}

const backendSource = readFileSync(backendPath, "utf8");
const frontendSource = readFileSync(frontendPath, "utf8");

const backendMatch = backendSource.match(/SUPPORTED_ATS\s*=\s*\{([\s\S]*?)\n\s*\}/);
assert(backendMatch, "Could not locate backend ApplicationFillReviewService.SUPPORTED_ATS.");

const frontendMatch = frontendSource.match(/SUPPORTED_FILL_REVIEW_ATS\s*=\s*\[([\s\S]*?)\]\s*as const/);
assert(frontendMatch, "Could not locate frontend SUPPORTED_FILL_REVIEW_ATS.");

const backendAts = [...new Set(quotedValues(backendMatch[1]))].sort();
const frontendAts = [...new Set(quotedValues(frontendMatch[1]))].sort();

assert(backendAts.length > 0, "Backend supported ATS list is empty.");
assert(frontendAts.length > 0, "Frontend supported ATS list is empty.");

const missingInFrontend = backendAts.filter((ats) => !frontendAts.includes(ats));
const extraInFrontend = frontendAts.filter((ats) => !backendAts.includes(ats));

assert(
  missingInFrontend.length === 0 && extraInFrontend.length === 0,
  [
    "Frontend fill-review ATS list is out of sync with backend support.",
    missingInFrontend.length ? `Missing in frontend: ${missingInFrontend.join(", ")}` : "",
    extraInFrontend.length ? `Extra in frontend: ${extraInFrontend.join(", ")}` : "",
  ].filter(Boolean).join(" "),
);

console.log(JSON.stringify({
  supported_fill_review_ats: frontendAts,
  count: frontendAts.length,
}, null, 2));
