const baseUrl = process.env.PREFLIGHT_API_URL ?? "http://127.0.0.1:8000";
const stamp = Date.now();
const email = `preflight-answer-audit+${stamp}@jobmatchkit.test`;
const password = "Password123!";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "content-type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    throw new Error(`${options.method ?? "GET"} ${path} failed with ${response.status}: ${text}`);
  }

  return body;
}

const auth = await request("/auth/register", {
  method: "POST",
  body: JSON.stringify({
    email,
    password,
    profile: {
      first_name: "Preflight",
      last_name: "Tester",
      phone: "555-0100",
      location: "Remote",
      years_experience: 7,
    },
  }),
});

assert(auth.access_token, "Register response did not include an access token.");
const headers = { authorization: `Bearer ${auth.access_token}` };

const answerPayload = {
  work_authorized_us: "yes",
  requires_sponsorship_now: "no",
  requires_sponsorship_future: "no",
  willing_to_relocate: "no",
  remote_preference: "remote",
  earliest_start_date: "2026-07-01",
  notice_period: "2 weeks",
  desired_salary: "$140k",
  work_authorization_notes: "Authorized to work in the US without sponsorship.",
  consent_to_use_answers: true,
  gender: "woman",
  race_ethnicity: "black_or_african_american",
  veteran_status: "not_a_veteran",
  disability_status: "prefer_not_to_answer",
  consent_to_use_demographics: false,
};

const savedProfile = await request("/application-profile", {
  method: "POST",
  headers,
  body: JSON.stringify(answerPayload),
});

assert(savedProfile.desired_salary === "$140k", "Saved profile did not round-trip desired_salary.");
assert(
  savedProfile.gender === "prefer_not_to_answer",
  "Demographic answer was retained without demographic consent.",
);

const exported = await request("/application-profile/export", { headers });
assert(exported.profile, "Export did not include the saved application profile.");
assert(exported.profile.desired_salary === "$140k", "Export did not decrypt desired_salary.");
assert(exported.profile.gender === "prefer_not_to_answer", "Export exposed unconsented demographic data.");

const audit = await request("/application-profile/audit?limit=20", { headers });
const actions = new Set(audit.map((entry) => entry.action));
assert(actions.has("upsert"), "Answer-vault audit is missing the upsert event.");
assert(actions.has("export"), "Answer-vault audit is missing the export event.");

const auditText = JSON.stringify(audit);
for (const sensitiveValue of [
  "$140k",
  "Authorized to work in the US without sponsorship.",
  "woman",
  "black_or_african_american",
]) {
  assert(!auditText.includes(sensitiveValue), `Audit log included sensitive value: ${sensitiveValue}`);
}

console.log(JSON.stringify({
  email,
  exported: Boolean(exported.profile),
  audit_actions: [...actions].sort(),
  audited_entries: audit.length,
}, null, 2));
