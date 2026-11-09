---
name: "Intern-Bot"
description: "A native application workshop with four miniature stations and a record-level decision inspector."
colors:
  bg: "#f7f6f1"
  surface: "#fffef8"
  surface2: "#e9ede4"
  border: "#b9c5ba"
  text: "#192d28"
  text2: "#40564e"
  text3: "#52635b"
  accent: "#a73e22"
  accent-hover: "#873016"
  on-accent: "#ffffff"
  selection: "#d6e5d7"
  info: "#275e78"
  warning: "#895019"
  danger: "#a93038"
  success: "#306342"
  neutral: "#52635b"
  panel: "#193530"
  panel-text: "#f4f4e7"
  panel-muted: "#cad9ca"
  panel-button: "#ffae78"
  panel-line: "#547169"
  panel-inset: "#27453d"
  bg-dark: "#15241f"
  surface-dark: "#20332b"
  surface2-dark: "#2b4036"
  border-dark: "#4f6357"
  text-dark: "#f0f2e7"
  text2-dark: "#cfdbca"
  text3-dark: "#adbfae"
  accent-dark: "#ffad75"
  accent-hover-dark: "#ffc298"
  on-accent-dark: "#251c12"
  selection-dark: "#405a48"
  info-dark: "#93cde5"
  warning-dark: "#f3ba70"
  danger-dark: "#ffa3a5"
  success-dark: "#abd6a8"
  neutral-dark: "#adbfae"
  panel-dark: "#112b25"
  panel-line-dark: "#56736a"
  panel-inset-dark: "#28473d"
  panel-on-button: "#272016"
  station-intake: "#f2b338"
  station-fill: "#39678a"
  station-verify: "#698d70"
  station-dispatch: "#e56c36"
  station-cream: "#f4ead1"
  station-ink: "#233932"
typography:
  page-title:
    fontSize: "32px"
    fontWeight: 700
  inspector-title:
    fontSize: "25px"
    fontWeight: 700
  brand:
    fontSize: "22px"
    fontWeight: 750
  section:
    fontSize: "18px"
    fontWeight: 650
  callout:
    fontSize: "15px"
    fontWeight: 600
  body:
    fontSize: "13px"
  scene-caption:
    fontSize: "12px"
  caption:
    fontSize: "11px"
  table-heading:
    fontSize: "11px"
    fontWeight: 600
rounded:
  control: "6px"
  pane: "8px"
  card: "10px"
  chip: "10px"
spacing:
  tight: "4px"
  inline: "6px"
  small: "8px"
  content: "12px"
  inset: "16px"
  page-y: "20px"
  page-x: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  button-ghost:
    textColor: "{colors.text2}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  button-danger:
    textColor: "{colors.danger}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "5px 8px"
  nav-selected:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.panel-text}"
    rounded: "{rounded.control}"
    padding: "7px 11px"
  filter-selected:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.text}"
    rounded: "{rounded.chip}"
    padding: "3px 12px"
  segment-selected:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.panel-text}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "16px 18px 18px"
  inspector:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.panel-text}"
    rounded: "{rounded.card}"
    padding: "16px 18px 18px"
  inspector-action:
    backgroundColor: "{colors.panel-button}"
    textColor: "{colors.panel-on-button}"
    rounded: "{rounded.control}"
    padding: "5px 12px"
---

# Design System: Intern-Bot

## Overview

**Creative North Star: "The Application Workshop"**

A student opens Intern-Bot to finish an application. At a glance they should be able to tell which job they are looking at, what the form actually contains, and whose turn it is. Four miniature workbenches make the preparation stages recognizable. The employer's question and the next available action sit alongside them in a native inspector.

The workshop is a model railway–scale object on a paper-colored desk. The surrounding app uses ink type, restrained borders and a deep green decision panel. The same four machines reappear in small nameplates on related screens. Interaction, evidence and approval live in Qt. The illustration can disappear and the workflow still works.

**Key Characteristics:**

- A named station, a physical tool and a distinct silhouette for each step.
- One selected application, one active run at a time, one primary action in its inspector.
- An observable field value, question or receipt behind every claim about progress.

![Application workshop with a fictional Lumen Analytics job selected. Its folder is at Verify. The inspector asks when the student can start and offers Answer questions.](docs/design/workshop.png)

The native captures in this guide use fictional records. Use the shipping source for behavior, the surface brief for intent and the approved prototype for the form and camera of the crew. The demo's sample timelines are illustrative. [Product brief](PRODUCT.md) · [Workshop direction](.impeccable/surfaces/application-workshop.md) · [Approved interactive prototype](docs/design-drafts/crew/index.html)

## Colors

The light palette pairs warm paper with dark green ink. In dark appearance the paper and inset surfaces become distinguishable greens and the action accent becomes peach. The inspector stays deep green in both appearances. Qt palette roles and the compiled QSS follow the macOS appearance at runtime. Read current colors from `TOKENS` when painting. To introduce a reusable color, change both `LIGHT` and `DARK` and reference its role in QSS. [Theme and shared widgets](gui/theme.py) · [Stylesheet](gui/styles.qss) · [Dark appearance](docs/design/dark.png)

| Native role | Light | Dark | Use |
| --- | --- | --- | --- |
| `bg` / `surface` / `surface2` | `#f7f6f1` / `#fffef8` / `#e9ede4` | `#15241f` / `#20332b` / `#2b4036` | Window paper, controls and tables, then quiet insets and hover. |
| `text` / `text2` / `text3` | `#192d28` / `#40564e` / `#52635b` | `#f0f2e7` / `#cfdbca` / `#adbfae` | Main reading, supporting information, then captions and placeholders. |
| `border` / `selection` | `#b9c5ba` / `#d6e5d7` | `#4f6357` / `#405a48` | Control edges and the selected native row. |
| `accent` / `accent_hover` / `on_accent` | `#a73e22` / `#873016` / `#ffffff` | `#ffad75` / `#ffc298` / `#251c12` | Primary action on paper, its hover and its text. The accent also marks focus and “Ready to approve.” |
| `info` / `warning` | `#275e78` / `#895019` | `#93cde5` / `#f3ba70` | Preparing or informational feedback, then a question or uncertain outcome. |
| `danger` / `success` / `neutral` | `#a93038` / `#306342` / `#52635b` | `#ffa3a5` / `#abd6a8` / `#adbfae` | Failure or removal, verified or applied, then queued or closed. Pair the tone with the exact label. |
| `panel` / `panel_inset` / `panel_line` | `#193530` / `#27453d` / `#547169` | `#112b25` / `#28473d` / `#56736a` | Inspector, inset question or secondary control, internal border. |
| `panel_text` / `panel_muted` / `panel_button` | `#f4f4e7` / `#cad9ca` / `#ffae78` | Same values | Inspector headline and question, supporting copy and the immediate action. |

**The Station Paint Rule.** Use a station's paint to identify the machine across states. Intake uses ochre, Fill uses blue, Verify uses sage and Dispatch uses orange. Reserve those paints for the models. A blue Fill worker can stand still during a warning and an orange Dispatch worker can wait for approval.

## Typography

Native labels inherit the Qt application font on macOS. Follow the final workshop overrides in the stylesheet. Create titles and copy with `label(text, role)`; the text can wrap. The texture on each physical nameplate uses bold Helvetica Neue with Arial and sans-serif fallbacks.

| Role | Effective size / weight | Use |
| --- | --- | --- |
| `pageTitle` | 32 px / 700 | One destination title. “Application workshop” changes to “Field crew” or “Applications” with the chosen view. |
| `inspectorTitle` | 25 px / 700 | Selected employer or first-use checklist. |
| Brand | 22 px / 750 | Intern-Bot in the top navigation. |
| `section` | 18 px / 650 | Form section or compact dialog nameplate. |
| Inspector callout | 15 px / 600 | The question or intervention that needs action. |
| Body / controls | 13 px / platform regular or control-specific weight | Values, statuses, editable fields and buttons. |
| `sceneCaption` / `caption` | 12 px / 11 px | Station or bar legend, then evidence, help and progress counts. Table headings use 11 px at 600. |

Write in sentence case. Keep long questions, answers and employer names as data. Wrap the full question in the inspector and the full value in the review tree. A concise table row may elide text where selection opens the complete record. ReadableTree measures wrapped paragraphs and long URLs against column width. [Shared labels and row sizing](gui/theme.py) · [Review implementation](gui/views/application_dialogs.py)

## Layout

The default desktop window is 1280 × 780 logical pixels. The minimum is 1040 × 660. A full-width navigation strip holds the brand, five destinations and the engine's current status. Page content usually has 24 px side margins, 20 px vertical margins and 12 px gaps. Settings uses a 16 px top margin. Shared cards use 18 px side padding, 16 px above and 18 px below.

In Applications, keep the title, attention counts and view controls together. The job link, Prepare application and Options occupy the next row. Below them, place the scene, filters and queue on the left and the inspector on the right. The horizontal splitter starts from 770 and 375 px with a 12 px handle. The inspector stack allows 330–470 px and its scroll area 340–460 px. Row height is 40 px. Search, sorting, record selection and the same inspector work in all three views.

**Size the table to its viewport.** When the table viewport falls below 660 px, hide Next step and Updated and stretch Company and Role. Keep the checkbox and Status columns. Re-evaluate as the user drags the splitter as well as when the window resizes. The inspector scrolls vertically. Put secondary actions in its menu and long notes behind “Tracking and notes.” The orthographic camera fits the entire machine row at the available scene aspect ratio. [Compact application window](docs/design/compact.png) · [Layout and column behavior](gui/views/tasks_view.py)

## Elevation & Depth

**The Workbench Shadow Rule.** Keep cast shadows in the miniature. Use surface tone and a single-pixel border to separate native layers. A selected paper row takes a sage fill. An active navigation item and the inspector take a deep green fill. Keep the UI edges clean so the miniature's cast shadows remain legible.

Model the workshop in a single orthographic view, looking down enough to read the tools and front nameplates together. Each bench has a stepped cream plinth, dark lip, numbered plate, individual machine, tool caddy and lamp. A shared directional light casts warm shadows from above and to the left. White ambient light keeps the shaded sides readable. Standard materials use roughness 0.72. Preserve the impression of painted, slightly rounded scale models. The charcoal Bar field uses fewer hues so the flags and bar heights carry the comparison. [Scene geometry, materials, lights and camera](gui/crew/scene.js)

## Shapes

Native buttons and inputs use a 6 px radius, tab panes and reading surfaces 8 px, cards, tables and filter chips 10 px. Inputs and tables retain a visible edge. Body and table surfaces are rectangular work areas. Keep the peach inspector action compact enough to sit beside the secondary menu.

The four workers share a squat jointed body, visor, antenna and boots. Their machines distinguish them in silhouette. Intake has stacked paper trays, Fill has an upright monitor and keyboard, Verify has a scanner arch over rollers and Dispatch has a slotted printer. The application is a small orange tabbed folder. An actual question raises the Verify worker's arm and displays a question placard. A recognized receipt is a paper slip at Dispatch.

Outside Applications, reuse the station renders already bundled in `gui/crew`. A standard `station_heading` reserves 91 × 70 px for the image, a compact dialog heading 62 × 48 px. The native text carries the screen name. Generate changes to this art from the same local scene so stills and live models agree. [Station heading](gui/theme.py) · [Bundled art and local viewport](gui/crew/)

## Components

### Native controls and navigation

Use `button`, `more_button`, `label`, `card`, `form_layout`, `MessageBar` and `restyle` from the shared theme. Dynamic properties select QSS variants. Forms use growing fields and left-aligned labels.

| Pattern | Decision |
| --- | --- |
| Primary and secondary | Give the current action a verb and object. Primary uses accent ink/fill contrast or peach on the inspector. Secondary uses a bordered surface. Buttons use 5 × 12 px vertical/horizontal padding. Ghost actions recede. Danger uses the danger text tone and a confirmation for destructive record changes. |
| View, filter and row selection | Workshop / Bar field / List are exclusive segments. A checked segment is dark green. A checked filter chip has a sage fill and accent border. A selected table row controls the inspector. Checked boxes separately choose eligible records for bulk operations. |
| Fields | Use native line edits, combos, checkboxes and file pickers for the corresponding data. A field takes 5 × 8 px padding, accent border on focus and muted surface/text when disabled. State why a consequential action is unavailable where the user makes that decision. |
| Navigation | Keep Applications, Profile, Answers, Settings, Scout in that order. The checked destination is dark green. Applications shows an attention count only when needed. Engine status includes a text label. Scout can flag an issue with an accessible description. |
| Feedback | Put a MessageBar near the action. Info and success messages clear after six seconds. Warnings and errors persist until superseded. Give a recovery step such as “Click Recheck on the board, then review it again.” Use plain text for external wording and escape values in rich text. |

### Applications and its three views

| Choose | Use it to | Interaction |
| --- | --- | --- |
| **Workshop** | Follow one selected application from posting to review or find the question holding it up. | The folder and lamp track its station. Select a native row to inspect another job. Click a bench for its explanation. Drag the canvas or focus it and use ← / → to rotate. |
| **Bar field** | Compare assessed fields across nearby applications, then open one that needs attention. | Tracks follow the sorted, filtered table in pages of up to three containing the selected row. Clicking a visible track selects that ID in Qt. The table reaches every other page. |
| **List** | Work through a long queue, search, compare statuses or operate entirely from the keyboard. | The scene is hidden and the table gains the space. The selection, actions and inspector use the same native paths. The view preference is saved locally. |

A new queue offers Edit profile, Choose resume and Paste link. A filtered queue with no rows offers Show all applications. A selected row opens a deep green inspector with company, role, status, platform, exact question or reason, one immediate action, and step or field evidence. Keep other eligible actions under More actions. “Run queue” handles queued or failed applications one at a time. [Native application view](gui/views/tasks_view.py)

### Station assignment and movement

The following rows describe what to draw for the selected application. Dispatch evidence has first priority, followed by the live work phase, then interventions and assessed fields. Read these rules from `crew_row`. Read the text and filter group from `status_meta`. Editing the user's tracking stage changes the tracker, independently of these engine facts. [Record schema](core/automation/models.py) · [Scene projection](gui/workshop.py) · [Status and actions](gui/views/tasks_view.py)

| Model evidence | Scene | Native meaning |
| --- | --- | --- |
| Queued, newly added, or no more specific checkpoint | Intake trays, stationary crew | The application awaits preparation or a native handoff. Show the actual status or intervention. |
| `running` | Use the live `work_phase` of Intake, Fill, Verify or Dispatch | Intake opens the posting and loads the profile, Fill writes known facts, Verify reads them back. A new section may return to Fill. `work_phase` is transient. |
| `needs_input` with a real question | Verify scanner, raised arm and question placard | Show the employer's actual question with “Answer questions.” A non-question intervention uses its own wording. |
| Non-running `needs_input` or `failed` with assessed fields | Verify, still | Inspect the recorded blocker and offer its applicable recovery. A generic error alone does not raise the question placard. |
| `ready_for_review` | Dispatch with the folder waiting, crew at rest | “Ready to approve.” Read the values through “Review application.” |
| `submission_attempted`, awaiting confirmation | Dispatch, folder disappears, no receipt slip | “Sent · receipt unconfirmed.” Offer “Check receipt” and manual confirmation. The attempt blocks a second send. |
| `submission_confirmed` | Receipt slip at Dispatch | “Employer receipt confirmed.” A recognized employer confirmation supplies this evidence. |
| `submitted_by_user` alone | Dispatch, stationary, no receipt slip | “Submitted by you” and “Submission confirmed by you.” The confirmation dialog explicitly asks whether the user submitted and saw employer confirmation. |

Selection changes the folder's subject and inspector. Only the selected application whose ID also equals the active worker ID can animate, and only while running or actively sending a ready application. Changing selection snaps to that record. An inactive question holds a static pose. A completed job, an idle queue and the other three workers stay still. Hidden documents suspend drawing. System reduced motion or disabling “Animate workers during an active application” under Settings → Automation → Workshop display suppresses work animation. User-directed rotation and native controls remain available.

If local Qt WebEngine or WebGL is unavailable, or the render process or context is lost, Qt paints four stills with a station underline or the native assessment bands and flags. The caption and inspector supply the text. List is always available. Keep the web channel display-only. It receives IDs, a company or hostname, station and aggregate dispositions. It can select a visible row or explain a station. Form values, full questions, documents and credentials belong outside the scene. [Projection and fallback](gui/workshop.py) · [Local channel](gui/crew/connect.js) · [Classic checkpoints](core/automation/engine.py) · [Request-mode checkpoints](core/automation/request_engine.py)

### Reading the Bar field

Each track represents one application. Within it, the assessments in stored order are divided into at most 18 contiguous bins of nearly equal size. Each bar's height encodes the verified fraction of its own bin, from a low base for zero through full height for one. Any blocked or needs-input assessment adds an amber flag, even if the other assessments in that bin passed. A bin of entirely intentionally omitted fields is slate. A missing assessment record yields no bar.

For example, 36 assessments produce 18 two-field bins. A bin with one verified and one blocked field is half of the verification range and carries a flag. A bin with two optional fields deliberately left blank stays low, slate and unflagged. Those two omissions still count as **resolved** in the native inspector. Show verified and omitted counts separately there. “No fields checked yet” covers an unassessed record. Use the field report for individual names and reasons. [Bin mapping and tests](tests/test_workshop.py)

![Bar field with three fictional tracks in table order. Lumen Analytics has an amber flag on its unresolved field. Harbor Robotics has no bars because it has no assessments.](docs/design/field.png)

### A walkthrough with one application

1. Paste the fictional Lumen Analytics posting and choose **Prepare application**. The active profile supplies a snapshot for this job. Intake opens the posting. When the engine reports Fill and Verify, the selected folder follows the real checkpoints.
2. The form asks “When can you start your internship?” The selected job stops at Verify. The inspector shows **Needs your answer**, the full question and **Answer questions**. Saving the final required answer lets preparation resume. A different employer can remain selected without its workers mimicking this activity.
3. Once preparation reaches review, Dispatch holds the folder. Choose **Review application** to read values the employer's form returned. Check the attached documents, flagged AI answers, declarations and deliberately blank optional fields. **Edit in browser** and **Recheck** update the review after an edit.
4. **Approve & send** authorizes this reviewed application and rechecks its values before sending. If another application is running, the review can still be read and sending waits. A changed form needs a fresh review. After a send attempt, check for the receipt. Only a recognized employer receipt draws the slip. If the student submitted it themselves and saw confirmation, record that separately with **I submitted it** or **Record employer confirmation**. [Review dialog capture](docs/design/review.png) · [Approval and receipt guards](core/automation/engine.py)

### Other destinations and dialogs

| Destination | What to put first | Native pattern and reference |
| --- | --- | --- |
| **Profile · Fill** | Named profile, essential facts still missing, unsaved changes and Save profile. | Left section list and a growing form. Switching profiles saves valid edits. Existing applications keep their own snapshot. A snapshot edit explicitly names its one-application scope. [Profile capture](docs/design/profile.png) · [Profile view](gui/views/profile_view.py) |
| **Answers · Verify** | The question, answer, profile, country and reuse scope. | Search questions, answers and alternate wordings. Use All answers / Needs confirmation / Approved. Expand child wordings. “AI · unconfirmed” stays visible until confirmation. Removing a wording and deleting the answer are distinct actions. [Answers capture](docs/design/answers.png) · [AnswersView](gui/views/application_dialogs.py) |
| **Settings · Dispatch** | What the option changes, which provider receives a request and what is stored locally. | Scrollable Automation, AI assistance and Safety and privacy tabs. Put the motion toggle under Automation → Workshop display. Mask keys. For connection tests show “Testing…” and a concrete result. Update privacy text for the selected endpoint and career-facts permission. [Settings capture](docs/design/settings.png) · [SettingsView](gui/main_window.py) |
| **Scout · Intake** | Selected profile, search or scan state, grouped openings and source evidence. | Put source, dates, quote and “Not stated” values in the evidence pane. Search settings disclose the context preview. “Prepare application” transfers the selected active, unexpired posting and its profile snapshot to Applications. [Scout capture](docs/design/scout.png) · [ScoutView](gui/views/scout_view.py) |

Use a compact station nameplate in task dialogs and keep the consequence on the final button. Application questions use the employer's control type, full wording and current “Remember for” scope. Stable facts can be reused more broadly. Declarations lock to this application and exact wording. The report and history expand below the immediate question.

Review before sending shows the profile, source, files and the Field / Value / Note tree. Put AI-generated values, declarations and optional omissions under “Check these first.” Keep long paragraphs readable at the actual column width. Older reviews missing a read-back value require Recheck. Edit in browser, Close and Approve & send have separate effects. The draft/compare assistant shows editable outgoing context, the named recipient, per-request consent and reviewable output. A filling guide shows which site and controls it covers before saving. [Question, review, snapshot and recipe dialogs](gui/views/application_dialogs.py) · [Draft and comparison dialog](gui/views/assistant_dialog.py)

### Extending a screen

Suppose a change asks for the employer's stated start date to be easier to find in Scout. Select a fictional result in the running Scout screen or a GUI fixture. Use the native capture as a layout reference and locate the existing “Start date” entry in `ScoutView.show_selected`. Move that entry earlier in the evidence pane. Read `item.evidence.get("start")`, preserve its source quote, escape both strings and keep “Not stated” when the employer supplied no date. Use the existing text browser and leave “Prepare application” tied to the selected posting's eligibility. Check one missing date, a long source quote, keyboard selection and a compact window. The same approach works for other evidence fields already on that record. [Scout layout reference](docs/design/scout.png) · [Evidence renderer](gui/views/scout_view.py)

### Keyboard and accessibility

| Scope | macOS behavior |
| --- | --- |
| Main window | ⌘1 Applications, ⌘2 Profile, ⌘3 Answers, ⌘4 Settings, ⌘5 Scout. ⌘N opens Applications and focuses Job link. ⌘F focuses application search. ⌘R invokes the selected application's enabled primary action. |
| Focused application table | Return / Enter invokes the row action. Delete or Backspace starts the applicable confirmation for checked or selected records. Typing in a text editor retains normal editing behavior. |
| Profile / Answers | ⌘S saves inside Profile. Delete and Backspace in the Answers tree act on the selected answer or wording. |
| Scene | Focus then ← / → rotates. The caption supplies the selected station and status or the track legend. Every consequential action has a native path. |

Give icon-only or ellipsis controls an accessible name and tooltip. Show selection through shape, contrast and text as appropriate. Focused navigation and view segments use 2 px accent borders. A focused inspector primary uses a 2 px light border. Keep the text count beside the progress indicator and the full employer step in the accessible description. Scope custom editing shortcuts to the focused native editor or item view. [Window navigation](gui/main_window.py) · [Editing shortcuts](gui/shortcuts.py) · [Table, stepper and inspector](gui/views/tasks_view.py)

## Do's and Don'ts

### Do

- Do bind every station, field count, question and receipt to the same run ID as the inspector.
- Do retain the exact question, the reviewed value and who confirmed a submission in native text.
- Do keep the decision and its action visible at compact width and with worker motion disabled.
- Do name the recipient, the data and the scope before a user sends context or approves an answer.

### Don't

- Don't advance a station on a timer, animate an idle queue or use the demo timeline as engine state.
- Don't represent an optional omission as a verified value, a send attempt as a receipt or a manual attestation as machine evidence.
- Don't put personal form contents or a submit action in the scene bridge.

### Acceptance checklist for a UI change

- [ ] At 1280 × 780 and 1040 × 660, select a long-named job with a full question. Read its status, reach the primary action and open secondary actions. Drag the splitter across the table's 660 px threshold.
- [ ] Select a different row while one job runs. Filter and sort, switch Workshop / Bar field / List, then select a track from the second page. The inspector, caption and table agree on the visible application ID.
- [ ] Compare mixed and wholly omitted bins, an unassessed row, and native verified/resolved counts. Confirm the question placard needs a real question.
- [ ] Inspect a ready review while a different job runs. Read the full values. Distinguish uncertain send, employer receipt and manual confirmation. Check that a second send is unavailable.
- [ ] Test light and dark appearance, the system reduced-motion preference, the in-app toggle and the still fallback. Navigate with the keyboard in List and confirm shortcuts stay scoped while an editor has focus.

Run the existing [workshop projection tests](tests/test_workshop.py), [GUI workflow tests](tests/test_gui.py) and [keyboard tests](tests/test_shortcuts.py) for affected paths. Review the scene and native focus on macOS when changing rendering or interaction.
