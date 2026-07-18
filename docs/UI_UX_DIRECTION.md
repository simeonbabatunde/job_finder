# JobMatchKit UI/UX Direction

This document translates the Influence Chart visual language into a JobMatchKit product experience.

## Source Reference

The target reference is the local project at:

`/Users/simeon/Documents/projects/influencer_chart`

Relevant files reviewed:

- `apps/web/app/globals.css`
- `apps/web/app/page.tsx`
- `apps/web/components/app-header.tsx`
- `apps/web/components/ranking-table.tsx`
- `apps/web/components/creator-card.tsx`
- `apps/web/components/search-form.tsx`
- `docs/HANDOFF.md`
- `docs/IMPLEMENTATION_PLAN.md`

## Design Principles

JobMatchKit should feel like a career operations console, not a marketing landing page.

- Put the usable product on the first screen.
- Frame the product as a smart job search assistant that matches roles to the user's resume and preferences, then packages the application materials.
- Favor clear navigation, compact sections, tables, forms, and status surfaces.
- Use a quiet color system with one confident accent.
- Make the selected matching profile, resume, preferences, run state, and application pipeline easy to scan.
- Keep motion subtle and purposeful.
- Avoid decorative gradient blobs, heavy hero panels, and nested cards.
- Use cards only for repeated items, modals, or genuinely framed tools.
- Keep cards at `8px` radius unless an existing component pattern requires otherwise.
- Use icons for controls where a familiar icon exists.
- Do not use visible in-app instructional text for obvious controls.

## Color Tokens

Use these CSS variables in `frontend/src/index.css`:

```css
:root {
  --page: #f6f8fb;
  --ink: #172033;
  --muted: #657084;
  --line: #dce2ea;
  --soft: #eef3f7;
  --accent: #3658a8;
  --accent-hover: #2a4585;
  --accent-soft: #e8edfb;
  --positive: #3f6fb5;
  --warning: #a16207;
  --warning-soft: #fef3c7;
  --danger: #b42318;
  --danger-soft: #fee4e2;
}
```

Use this token system instead of one-off indigo/violet classes:

| Current pattern | Replacement |
| --- | --- |
| `bg-slate-50` page backgrounds | `bg-[var(--page)]` |
| `text-slate-900` primary text | `text-[var(--ink)]` |
| `text-slate-500` secondary text | `text-[var(--muted)]` |
| `border-slate-200` | `border-[var(--line)]` |
| `bg-slate-100` | `bg-[var(--soft)]` |
| `bg-indigo-600` primary action | `bg-[var(--accent)]` |
| `bg-indigo-50 text-indigo-700` | `bg-[var(--accent-soft)] text-[var(--accent)]` |
| Emerald success | `text-[var(--positive)]` plus a soft green background |

## Typography

- Keep Inter.
- Use semibold rather than extra-black headings for a quieter dashboard feel.
- Use uppercase metadata sparingly for section labels, table headers, and compact status chips.
- Avoid viewport-scaled font sizes.
- Keep letter spacing at `0` except short uppercase metadata where the existing Influence Chart style uses modest tracking.

## Layout Target

### App Shell

The app shell should stay dashboard-first:

- Top app header, white background, bottom border.
- Brand block: small domain or app label, then "JobMatchKit".
- Navigation: Dashboard, Applications, Account, and Admin when permitted.
- Account actions: plan chip, email, sign out.
- Main background: `var(--page)`.
- Content max width: `max-w-7xl`, horizontal padding `px-5`, vertical rhythm `py-6`.

### Dashboard First Screen

The first screen should show the actual workflow:

- Top overview strip: selected matching profile, resume, preference, profile, and quota readiness.
- Profile selector band: current saved profile, attached resume, target-role summary, and actions to switch/add/rename/archive.
- Main setup panel: Resume, Preferences, and account Profile in one compact workflow with divider-separated sections.
- Right action rail: matching controls with quota, plan state, and package-generation status.
- Right recent matches panel with compact job rows; the full table lives on the Applications page.
- Full application pipeline lives on the Applications page.

Use full-width bands or grids instead of a single card containing the entire app.

### Matching Profile Selector

The selector should feel operational, not like account settings:

- Show current profile name, attached resume filename, target-role summary, and last-used state.
- Use a compact select/menu for switching profiles.
- Provide clear actions: New profile, Duplicate, Rename, Archive.
- Do not hide the selected profile in tiny nav text; it should be visible near Start Matching.
- Account-level profile/contact details remain separate from matching profiles.

### Setup Sections

Resume, Profile, and Preferences should share field styling:

- Use one white setup panel with divider-separated workflow sections on the dashboard.
- Use compact section headers and status chips instead of a side label rail.
- Inputs use `bg-white`, `border-[var(--line)]`, and focus border `var(--accent)`.
- Multi-selects should behave like menus with checkboxes, not custom ad hoc dropdowns where possible.
- Sliders or steppers are preferred for numeric thresholds such as match score.

### Matching Panel

The run control should look operational:

- Header: "Match and package jobs".
- Metrics: selected matching profile, minimum match, date range, selected sources, and package state.
- Primary action: "Start matching".
- Secondary actions: "Preview matches", "Refresh history" where supported.
- Browser-form automation is retired; the supported flow is package generation plus manual employer links.

### Application History

Use the Influence Chart table language:

- Rounded table wrapper with border.
- Soft header row.
- Columns: Role, Company, Profile, Fit, Status, Updated, Actions.
- Status chips should map to a stable palette.
- Default display remains the most recent 5 matches, with the full history available through the `/applications` route.

### Application Package Modal

Keep the modal, but make it more utilitarian:

- Header uses ink/accent, not an indigo gradient.
- Tabs should be compact segmented controls.
- Tabs use lucide icons.
- Use document-like panels for cover letters and summaries.
- Status pipeline should use consistent status chips.
- Copy/PDF/Open Job should be icon buttons with labels or tooltips.

### Auth Screens

The login/register modal should use the same product shell and tokens:

- No decorative background blobs.
- `rounded-lg` panel.
- Compact tabs.
- Provider buttons, if added later, should be clear text plus icon rows.
- Error and success states use the shared danger/success tokens.

### Admin

The admin panel should stay aligned with the app shell:

- Same header and max-width container.
- Board selection as check rows.
- Results wanted as number input or stepper.
- Save action in a sticky or clear footer row.

## Component Work

Create a small component layer before restyling every page:

- `AppHeader`
- `PageShell`
- `SectionHeader`
- `Button`
- `IconButton`
- `Field`
- `StatusChip`
- `DataTable`
- `EmptyState`
- `ProgressBar`

Do not add a large UI framework yet. Tailwind primitives plus local components match the Influence Chart approach.

## Icon Direction

Add `lucide-react` for:

- Upload
- FileText
- User
- SlidersHorizontal
- Search
- Play
- RefreshCw
- ExternalLink
- Download
- Copy
- X
- Check
- AlertTriangle
- BriefcaseBusiness
- Settings

Use icons or text-only status chips rather than emoji indicators.

## Responsive Behavior

- Dashboard columns collapse to one column below `lg`.
- Tables keep horizontal scroll rather than squeezing text into unreadable columns.
- Button text must not overflow on mobile.
- Fixed-format elements such as status chips, score pills, icon buttons, and table cells need stable dimensions.
- Modals should use max height with internal scrolling.

## Accessibility

- Every icon-only button needs an accessible label and tooltip if the icon is not obvious.
- Use actual buttons for actions and links for navigation.
- Inputs must have labels.
- Focus rings should be visible and use the accent color.
- Status messages should not rely on color alone.

## Acceptance Criteria

The UI redesign is done when:

- The first viewport is a usable dashboard, not a hero card.
- Color usage matches the Influence Chart token family.
- The old Vite template CSS is removed.
- There are no decorative gradient blobs or one-off indigo/violet gradients.
- Main workflow pages share a header, field style, section style, buttons, status chips, and table style.
- Application history is scannable on desktop and mobile.
- Resume/Profile/Preferences/Start matching feel like one coherent workflow.
- Auth and admin screens no longer feel visually separate from the main app.
