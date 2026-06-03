# Intern-Bot Autofill Extension

This is the browser-side filling engine for Intern-Bot. It keeps the Python/PySide app as the profile and task manager while moving Workday field interaction into the active Chrome tab.

## First Workflow

1. In the desktop app, open `Profile` and click `Export Extension JSON`.
2. In Chrome, load the built or dev extension.
3. Open the extension popup and import `data/extension_profile.json`.
4. Open a Workday application page.
5. Click `Fill visible fields`.
6. Review highlighted fields before continuing.

Green outlines mean the extension filled a field. Amber outlines mean the field needs review.

## Development

```bash
npm install
npm run dev
```

WXT will create a development extension in `.output/`. Load that unpacked extension in Chrome.

## Design Notes

- The content script scans visible fields and decides what is safe to fill.
- `public/page-bridge.js` runs in the page context so React-controlled fields receive native value updates plus `input`, `change`, and `blur` events.
- The extension never submits applications. Review and final submission stay manual.
