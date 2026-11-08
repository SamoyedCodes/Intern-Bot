---
target: "Applications: paste, answer, review and send"
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:/Users/example/Documents/GitHub/Intern-Bot/gui/views/tasks_view.py"
target_fingerprint: "sha256:01cf5b5564fcc613f4a4028643fc1e966edcbdfcc3cb39d70ef0b3f833d6eeb7"
target_path: /Users/example/Documents/GitHub/Intern-Bot/gui/views/tasks_view.py
timestamp: 2026-11-08T14-40-24Z
slug: gui-views-tasks-view-py
---
# Applications UI critique — 8 November 2026

Target: gui/views/tasks_view.py and application_dialogs.py. Mode: Operate. Two independent assessments; current native Qt light/dark captures at 1280×780 and 1040×660, with fictional data. No live employer actions.

The local application desk has coherent native styling and a direct paste-to-prepare entry. The main weakness is that answering and approving still require operating the automation system. Preserve explicit approval, field verification, and receipt safeguards.

| Heuristic | Score /4 |
|---|---:|
| Visibility of system status | 3 |
| Match with real world | 2 |
| User control and freedom | 3 |
| Consistency and standards | 3 |
| Error prevention | 3 |
| Recognition over recall | 2 |
| Flexibility and efficiency | 3 |
| Aesthetic and minimalist design | 2 |
| Error recovery | 2 |
| Help and documentation | 2 |
| Total | 25/40 |

Strengths: Paste/Enter and a persistent entry field fit repeat use. Approval rechecks filled values and prevents duplicate sends; AI answers are distinguished from profile facts.

## Priorities

1. P1 — Approval truncates paragraphs. Career aspirations is elided in both themes, so the user cannot read what they approve without hovering. Use readable multiline rows and semantic section titles. Suggested command: harden.
2. P1 — Supported sizes clip actions and status. The unsupported-site detail exceeds its scroll viewport at 1280; at 1040 fixed columns disappear under disabled horizontal scrolling. Use one main action, secondary menus and responsive table columns. Suggested command: adapt.
3. P2 — Missing-answer dialog exposes system administration. Exact wording, answer type, reuse scope and empty diagnostics compete with the actual question. Show the readable question and answer first; disclose reuse/type controls and diagnostics. Suggested command: distill.
4. P2 — Recovery and tracking compete with progress. Teaching choices and manual submission appear beside the normal next action. Put secondary recovery in the menu, make tracking collapsible, and explain unsupported status plainly. Suggested command: clarify.

Cognitive load: high in exceptions and approval; single focus, one decision at a time, working memory and progressive disclosure fail. Grouping and basic hierarchy are consistent. The answer-type menu presents six choices.

Personas: Jordan cannot tell whether Resume fixes a missing answer. Alex must reconstruct generic page groups. Sam encounters clipped controls and hover-only long answers. Native screen reader behavior was not tested.

Minor observations: ready state can say Not started; raw group identifiers appear in review; progress text can fall to 9px. Tracking detail is available but consumes the main task area.

Questions skipped: the user explicitly asked to fix the critique findings; product goal and native visual direction were already established.
