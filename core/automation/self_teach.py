"""Self-teach: the AI drives the first application on an unsupported site, page by page, up to its review page,
and what worked becomes a site recipe that later applications replay without AI.

The AI sees what `ai_autofill` already may (labels, options, button text, profile fact names; career facts only when
allowed) plus a short tag/role/class outline of each control. It chooses values only as profile-fact links, saved
answers or, with career facts allowed, short factual answers, all saved as unconfirmed AI answers. It never sees
the values filled in, never submits, never signs in or creates an account."""
import asyncio
import json
import re

from core.automation.answers import applicable, fact_allowed, fact_catalog, question_for, resolve
from core.automation.assistant import askable, career_facts, checked, generate_text, matchable
from core.automation.engine import ApplicationEngine
from core.automation.models import ApprovedAnswer, employer_key, normalized, site_key
from core.automation.privacy import redact
from core.automation.recipes import OBSERVE, build_from_trace, form_field, recipe_for, same, save_recipe

WIDGETS = ("native", "aria-combobox", "click-list")
MAX_PAGES = 25
RESUME = re.compile(r"\bresume\b|résumé|\bcv\b|curriculum vitae", re.I)
CALLS_PER_PAGE = 3
# A visible challenge, not the invisible reCAPTCHA script many ordinary forms load.
CAPTCHA = """() => [...document.querySelectorAll('iframe')].some(f => f.getClientRects().length && f.offsetHeight > 30 &&
  /captcha|turnstile|challenge/i.test((f.src || '') + ' ' + (f.title || '')))"""


class SelfTeacher(ApplicationEngine):
    """Reuses the engine's pause/cancel, interventions and checkpoints; drives the page through Playwright directly."""

    async def start(self, run, profile, page, cfg):
        self._pause = self._cancel = False
        self.cfg_facts = cfg["facts"]
        run.status, run.interventions = "running", []
        run.profile_snapshot = run.profile_snapshot or profile.model_copy(deep=True)
        self.checkpoint(run)
        host, trace = site_key(page.url), []
        try:
            message = await self.teach(run, profile, page, cfg, trace)
        except Exception as exc:
            message = f"Self-teach stopped ({type(exc).__name__}). Check the page in Chromium; what was learned so far is kept as a draft recipe."
        if trace:
            draft = build_from_trace(host, trace)
            previous = recipe_for(self.store, page.url, approved=False)
            save_recipe(self.store, previous.merged(draft) if previous else draft)
        if run.status == "running":
            if self._cancel:
                run.status = "cancelled"
            else:
                self.intervene(run, "Paused by you. Resume when ready." if self._pause else message)
        self.checkpoint(run)
        return run

    async def teach(self, run, profile, page, cfg, trace):
        last = None
        for _ in range(MAX_PAGES):
            if self._pause or self._cancel:
                return ""
            observed = await page.evaluate(OBSERVE)
            if any(f["kind"] == "password" for f in observed["fields"]) or await page.evaluate(CAPTCHA):
                return "This page asks you to sign in, create an account or prove you're human. Do that in Chromium, then let AI teach itself again."
            labels = sorted(f["key"] for f in observed["fields"])
            if (observed["url"], labels) == last:
                return "The page didn't change after the AI continued. Check it in Chromium, then try again or teach it by filling it in."
            last = (observed["url"], labels)
            step = {"fields": [], "advance": None, "submit": None}
            trace.append(step)
            decision, failed = {}, []
            for _ in range(CALLS_PER_PAGE):
                decision = await self.decide(run, profile, observed, cfg, failed)
                failed = await self.act(run, profile, page, observed, decision, step)
                observed = await page.evaluate(OBSERVE)
                if not failed or self._pause or self._cancel:
                    break
            chosen_radios = {f["label"] for f in observed["fields"] if f["kind"] == "radio" and f["value"] is True}
            unanswered = [f for f in map(form_field, observed["fields"]) if f.required and f.value in ("", False) and f.label not in chosen_radios
                          and resolve(f, profile, run, self.store.answers()).value is None]
            submit = [b for b in observed["buttons"] if b["kind"] == "submit"]
            if unanswered:
                for field in {f.label: f for f in unanswered}.values():  # A radio question once, not once per option.
                    self.intervene(run, f"Answer “{field.label}” so the AI can continue.", "answer", field)
                return ""
            chosen = next((b for b in observed["buttons"] if b["id"] == decision.get("advance")), None)
            if decision.get("done") == "review" or (submit and (not chosen or chosen["kind"] == "submit")):
                step["submit"] = submit[0] if len(submit) == 1 else None
                return (f"The AI filled the application up to its review page and drafted a recipe for {site_key(page.url)}. "
                        "Review the recipe, check the form in Chromium and submit it yourself, then press I submitted it.")
            if not chosen or chosen["kind"] == "submit":
                return decision.get("reason") or "The AI couldn't tell how to continue. Continue in Chromium, then let AI teach itself again."
            step["advance"] = chosen
            await page.click(f'[data-intern-button="{chosen["id"]}"]')
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(1)  # Let a single-page form render its next step.
        return f"The application went past {MAX_PAGES} pages. Check it in Chromium."

    async def decide(self, run, profile, observed, cfg, failed=()):
        """One AI call for this page: a value source, widget and (for unlabelled controls) a label per field, and the button to continue."""
        answers = self.store.answers()
        known = [a for a in applicable(answers, profile, run) if matchable(a)]
        fields = {}
        for i, f in enumerate(observed["fields"], 1):
            field = form_field(f)
            if field.kind in {"password", "hidden"} or field.disabled or field.readonly:
                continue
            fields[f"f{i}"] = dict(label=field.label, kind=field.kind, control=f["outline"], required=field.required,
                                   answered=resolve(field, profile, run, answers).value is not None, may_answer=askable(field),
                                   **({"option": field.option} if field.option else {}), **({"options": field.options[:100]} if field.options else {}),
                                   **({"unlabelled": True} if f["named"] or not field.label else {}))
        context = json.dumps({"fields": fields, "buttons": {b["id"]: dict(text=b["text"], kind=b["kind"]) for b in observed["buttons"]},
                              "saved_questions": {f"s{i}": a.question for i, a in enumerate(known, 1)}, "profile_facts": fact_catalog(profile),
                              **({"did_not_take": list(failed)} if failed else {})}, ensure_ascii=False)
        if cfg["facts"]:
            context += "\n\nCareer facts:\n" + redact(json.dumps(career_facts(profile), ensure_ascii=False), profile)
        run.ai_requests += 1
        self.store.record_event(run.id, "ai_request", run.stage, f"Self-teach with {cfg['name']} {'on this Mac' if cfg['local'] else '(cloud)'}: "
                                f"{len(fields)} fields, {len(observed['buttons'])} buttons; career facts {'included' if cfg['facts'] else 'not sent'}.")
        reply = await asyncio.to_thread(generate_text, cfg, "self_teach", context)
        try:
            decision = json.loads(re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", reply, flags=re.S), re.S)[0])
        except (TypeError, ValueError):
            raise ValueError("The AI reply was not a page plan; nothing more was filled.") from None
        return decision if isinstance(decision, dict) else {}

    def value_for(self, run, profile, field, choice, known):
        """The approved value for a field, else the AI's choice checked against the same closed sets as ai_autofill (saved as an AI answer)."""
        answers = self.store.answers()
        found = resolve(field, profile, run, answers)
        question = question_for(field, profile)
        if found.value is None and field.kind == "file" and profile.resume_path and RESUME.search(field.label) and not re.search(r"cover", field.label, re.I):
            # An upload that asks for a resume gets your profile's resume, kept as an unconfirmed answer like any other the AI filled.
            answer = ApprovedAnswer(question=question, value=profile.resume_path, profile_name=run.profile_name, scope="employer", scope_key=employer_key(run.job_url), origin="ai")
            self.store.save_answer(answer)
            return resolve(field, profile, run, self.store.answers()).value
        if found.value is not None or found.omit or not askable(field) or not isinstance(choice, dict):
            return found.value
        if isinstance(choice.get("saved"), str) and (m := re.fullmatch(r"s?(\d+)", choice["saved"])) and 1 <= int(m[1]) <= len(known):
            answer = known[int(m[1]) - 1]
            answer.variants.append(field.label)
        elif isinstance(choice.get("fact"), str) and fact_allowed(choice["fact"], fact_catalog(profile)):
            answer = ApprovedAnswer(question=question, fact=choice["fact"], profile_name=run.profile_name, scope="global", origin="ai")
        elif self.cfg_facts and isinstance(choice.get("value"), (str, bool)) and (value := checked(field, choice["value"])) is not None:
            answer = ApprovedAnswer(question=question, value=value, profile_name=run.profile_name, scope="employer", scope_key=employer_key(run.job_url), origin="ai")
        else:
            return None
        self.store.save_answer(answer)
        self.store.record_event(run.id, "answer_ai", run.stage, f"Self-teach answered “{field.label}”. Confirm it under Answers.")
        return resolve(field, profile, run, self.store.answers()).value

    async def act(self, run, profile, page, observed, decision, step):
        """Fill each field with its value, trying the AI's widget first and the others after. Returns the labels that still failed."""
        known = [a for a in applicable(self.store.answers(), profile, run) if matchable(a)]
        choices = decision.get("fields") if isinstance(decision.get("fields"), dict) else {}
        failed = []
        for i, captured in enumerate(observed["fields"], 1):
            if self._pause or self._cancel:
                return []
            choice = choices.get(f"f{i}") if isinstance(choices.get(f"f{i}"), dict) else {}
            field = form_field(captured)
            label = str(choice.get("label") or "")[:120] if (captured["named"] or not field.label) else ""
            if label:
                field.label = label  # The AI named an unlabelled control; the recipe keeps that name.
            if field.kind in {"password", "hidden"} or field.disabled or field.readonly:
                continue
            value = self.value_for(run, profile, field, choice, known)
            if value is None or (field.kind == "radio" and normalized(field.option) != normalized(str(value))):
                continue
            if field.kind != "radio" and field.value not in ("", False) and same(field.value, value):
                continue
            hint = choice.get("widget") if choice.get("widget") in WIDGETS else captured["widget"]
            for widget in dict.fromkeys((hint, *WIDGETS)):
                if await self.fill(page, captured, field, value, widget) and await self.took(page, captured, value):
                    step["fields"].append((captured, label, widget))
                    break
            else:
                failed.append(field.label)
        return failed

    async def fill(self, page, captured, field, value, widget):
        control = page.locator(captured["selector"])
        try:
            if widget == "native":
                if field.kind == "file":
                    await control.set_input_files(str(value))
                elif field.kind in {"checkbox", "radio"}:
                    # A click on the input itself, as the extension does: React sites notice it, and styled forms often hide the input behind its label.
                    await control.evaluate("(e, want) => { if (e.checked !== want) e.click(); }", value is True or field.kind == "radio")
                elif field.kind.startswith("select"):
                    await control.select_option(label=str(value))
                else:
                    await control.fill(str(value))
                return True
            await control.click()
            if widget == "aria-combobox":
                await control.fill(str(value)) if await control.evaluate("e => e instanceof HTMLInputElement") else await page.keyboard.type(str(value))
            option = page.get_by_role("option", name=str(value), exact=True)
            await option.first.click(timeout=2000)
            return True
        except Exception:
            return False

    async def took(self, page, captured, value):
        """Read the control back: what the form now shows must be exactly the value."""
        await asyncio.sleep(.2)
        current = next((f for f in (await page.evaluate(OBSERVE))["fields"] if f["key"] == captured["key"]), None)
        if not current:
            return False
        if current["kind"] == "radio":
            return current["value"] is True
        return same(current["value"], value) if current["kind"] != "file" else bool(current["value"])


def consent_text(cfg):
    where = "on this Mac" if cfg["local"] else f"to {cfg['name']} (cloud)"
    facts = "Your career facts are included (your setting)." if cfg["facts"] else "Your career facts are not sent (your setting)."
    return (f"The AI fills this application itself, one request per page (up to {CALLS_PER_PAGE} when a field needs another try), "
            f"sent {where}. Each request holds the page's field labels, options and button text, a short description of each control, "
            f"and the names of your profile fields, never their values. {facts}\n\n"
            "It stops at the review page and never submits, signs in or creates an account. "
            "Answers it chooses are marked AI · unconfirmed and block automatic sending until you confirm them.")
