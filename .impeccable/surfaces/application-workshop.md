# Application workshop

Mode: Operate. Scope: Intern-Bot's five native macOS destinations.

## Direction contract

**Thesis.** A student can see which part of an application the bot has reached, what it checked and which decision belongs to them.

**Own world.** Paper-colored native work surfaces, ink type, a deep green inspector, warm orange actions and a miniature model railway–scale workshop. Four individually tooled benches make Intake, Fill, Verify and Dispatch recognizable by silhouette.

**Story.** Paste a job, follow its folder, answer the actual missing question, review the verified fields and check the employer receipt. A single queue processes the work. Scout supplies postings. Profile and Answers supply facts. Settings controls automation, assistance and privacy.

**First viewport.** Full-width navigation, job input and view controls. The left side holds the workshop plus the queue. The selected application's question or approval and its primary action occupy the right inspector. The compact window keeps the decision and hides lower-priority table columns.

**Form.** The user chose the working Application Crew prototype in `docs/design-drafts/crew/`, following the Datamatics bar-field exploration (seed:8753ab445cc98073). Select a job to move its folder to the reported station. Switch to Bar field to compare real assessment bands or List to work entirely in native controls.

**Finish.** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Completed verification

The native macOS capture round covered the five destinations, question and review dialogs, Workshop, Bar field and List, plus compact and dark appearance. The finish reviewer returned `ship` after scoring all four requested fixes resolved.

Native interaction checks exercised station explanations, track selection, camera rotation, live phase updates, animation and its off switch, and the distinction between review, send attempt and receipt. The full suite passed 512 tests. The supplied-profile acceptance test skipped because it requires an explicit local profile.

The standalone guide is `DESIGN.md`, with machine-readable extensions in `.impeccable/design.json`. Native examples are in `docs/design/`. The raster provenance scan passed for all 17 files in `gui/crew/`, `docs/design/` and `docs/design-drafts/`.
