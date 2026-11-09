# Product

<!-- impeccable:product-schema 1 -->

## Platform

Native macOS desktop. PySide6 widgets and QSS host an embedded local Three.js scene.

## Users

One student running their own internship search on their Mac today; the product may later be shared with other students. They come back daily in short sessions: paste a job URL, answer whatever the bot could not, check what it filled, submit, and keep track of where every application stands.

## Product Purpose

Intern-Bot is a local application desk. It keeps named profiles and approved answers, fills application forms in a visible Chromium window using 28 site-specific adapters, verifies every field it writes, and tracks each application from saved to offer. Scout finds and verifies open internships for a profile. Success: more applications sent with less retyping, and the user always knows what is waiting on them.

## Positioning

Everything runs locally and the user stays in control of submission. Field values are read back and verified; AI answers are marked unconfirmed and block automatic submission; a submission only counts on a recognised employer receipt or the user's own confirmation.

## Operating Context

- Main areas: Applications (list, detail, run queue), Scout (daily scans, verified postings), Profile, Answers, Settings.
- Application states include Queued, In progress, Needs your answer, Ready for review, Submitted by you, Interviewing, Offer, Closed; teach flows for unsupported sites.
- Keyboard-driven: ⌘N new application, ⌘R run, ⌘S save profile, ⌘5 Scout.
- Follows macOS light and dark appearance.

## Capabilities and Constraints

- Native Qt controls handle every application action. WebGL visualizes the same records and has a still-image fallback.
- Employer logins via 1Password CLI; API keys in the macOS keychain.
- Optional AI providers (local, Claude, OpenAI, Gemini, DeepSeek, OpenAI-compatible).
- Automatic submission off by default, authorized per application.

## Brand Commitments

Name: Intern-Bot. Voice: plain, factual, second person, no hype ("Answer 1 question to continue").

## Evidence on Hand

- Native screenshots with fictional records are in `docs/design/`. The approved interactive prototype lives in `docs/design-drafts/crew/`.
- No real users, testimonials or metrics; do not invent them.

## Product Principles

1. What needs the user comes first: every screen answers "what is waiting on me?"
2. The user submits; automation never claims success it cannot verify.
3. Local and private by default; say plainly what leaves the Mac.
4. Fast repeat use beats first-run spectacle.

## Accessibility & Inclusion

Follow macOS light/dark, keyboard access for every primary action, status never carried by colour alone.
