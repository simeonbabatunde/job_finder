# Browser Automation Retirement

`Apply with assistant` and `Application Prep` have been removed from JobMatchKit. The app no longer attempts to fill employer forms, prepare live browser sessions, inspect submit controls, save browser screenshots, or generate Playwright traces.

Current product scope:

- Search official company and job-board sources.
- Score jobs against the resume and preferences.
- Save strong matches to the pipeline.
- Generate downloadable application packages.
- Let users open employer application links manually.

Retired backend routes now return `410 Gone` so old tabs, scripts, or extensions fail clearly instead of starting browser automation. Historical database tables remain only for migration compatibility and old-account cleanup/export safety.
