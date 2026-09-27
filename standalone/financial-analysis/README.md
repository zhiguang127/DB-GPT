# Single-file financial analysis demo

From the repository root, with the existing `web/node_modules` installed:

```powershell
node standalone/financial-analysis/build.cjs
```

Output: `DB-GPT-Financial-Analysis-Demo.html` in the repository root. Copy only this
file to the recipient. Double-click to open it in Chrome or Edge. No server,
installation, internet access or adjacent assets are needed at runtime.

This independent Webpack build imports the current financial-analysis components,
mock data, CSS module, chart components, and native Manus Agent panel unchanged.
It does not use or modify Next.js configuration, package scripts, or source files.
Imports are bundled eagerly into one inline classic script. All emitted CSS is
embedded in a style element; Ant Design's runtime styles remain inside that script.
Logos/sidebar images are embedded as data URIs. Icons render as inline SVG.

Standalone-only adapters replace Next routing/dynamic loading, the backend chat
context, backend attachment downloads, and the general-purpose Markdown artifact
renderer. The sidebar preserves DB-GPT styling with outbound actions inert.
Light/dark mode and sidebar collapse use in-memory React state. No localStorage,
API, external fonts, CDN, analytics, or PDF download is needed. Source previews
retain the current mock's extracted excerpts; this demo does not contain the
original full annual-report PDF.

The HTML includes a restrictive CSP (`connect-src 'none'`) and passive in-memory
diagnostics at `window.__DEMO_DIAGNOSTICS__` for runtime verification. It does not
silently intercept or hide failed network requests. Build intermediates and the
source-integrity/build report live in ignored `.work/`; they are not deliverables.

The entry explicitly passes `mockReportData` into the shared page. Application
components receive a `ReportData` snapshot and do not import `mock-data.ts`.

Run the data/rendering regression without a browser:

```powershell
node standalone/financial-analysis/test-data.cjs
```

To verify bundling without replacing the delivered demo, pass an output path
whose parent directory already exists:

```powershell
node standalone/financial-analysis/build.cjs .work/financial-analysis/demo-round2.html
```

## Saved-report HTML exports

Build the offline runtime separately from the delivered mock demo:

```powershell
New-Item -ItemType Directory -Force .work/financial-analysis | Out-Null
node standalone/financial-analysis/build.cjs .work/financial-analysis/export-runtime.html --export-runtime
```

The backend inserts the saved report JSON into this runtime when the user selects
HTML export in the existing Files panel. The runtime imports the same React report
components, with no mock dataset. The result contains its data, styles, scripts,
charts and source excerpts. It requires JavaScript but no network connection.
Original PDF pages/downloads and online questions remain application features;
the offline source panel explicitly shows excerpts. JSON export needs no build.

The backend defaults to `.work/financial-analysis/export-runtime.html` alongside
the repository's `skills` directory. Set `DBGPT_FINANCIAL_EXPORT_RUNTIME` to an
absolute path for another deployment location. Rebuild after report UI changes.
Already registered exports remain immutable for their report revision.

Stateful history/export checks (pass an installed React 18 test-renderer path):

```powershell
node standalone/financial-analysis/test-history-exports.cjs <react-test-renderer-path>
```

These checks and the existing SSR/layout checks do not replace browser acceptance.
