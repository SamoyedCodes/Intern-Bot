"""Site recipes: how to drive one unsupported careers site, learned once (by watching you, or by the AI) and replayed for free.

A recipe holds no personal values, only labels, selectors, widget names and the receipt wording. Answers stay in the answer bank."""
import re
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from core.automation.answers import ALIASES, FACT, fact_catalog, linked, question_for, resolve
from core.automation.fields import FormField
from core.automation.models import ApprovedAnswer, employer_key, normalized, now, site_key

HERE = Path(__file__).parent
SCAN = (HERE / "scan.js").read_text()
# One page as plain data: its fields (scan.js plus a durable selector and widget hint), buttons and headings.
OBSERVE = f"() => ({(HERE / 'observe.js').read_text()})({SCAN})"
# Teach mode: report the page to the app on every button click, before the click navigates.
TEACH = f"""() => {{
  if (window.__internTeach) return;
  window.__internTeach = true;
  const observe = {OBSERVE};
  document.addEventListener('click', event => {{
    const target = event.target.closest?.('button,input[type=submit],input[type=button],a,[role=button]');
    if (!target || typeof window.internTeach !== 'function') return;
    const page = observe();
    page.clicked = page.buttons.find(b => b.id === target.getAttribute('data-intern-button')) || null;
    window.internTeach(page);
  }}, true);
  // Some sites swap a file input for an attachment card once a file is chosen: report the page while the file is still there.
  document.addEventListener('change', event => {{
    if (event.target?.type !== 'file' || typeof window.internTeach !== 'function') return;
    window.internTeach({{...observe(), clicked: null}});
  }}, true);
}}"""

Selector = Field("", max_length=300)
HOST = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


class RecipeField(BaseModel):
    css: str = Selector         # durable selector, when the control has one
    match: str = Field("", max_length=300)  # else the control's own label text
    label: str = Field("", max_length=300)  # the label the answer bank knows it by, when the form's is missing or odd
    kind: str = Field("", max_length=20)
    widget: Literal["native", "aria-combobox", "click-list"] = "native"

    @model_validator(mode="after")
    def located(self):
        if bool(self.css) == bool(self.match):
            raise ValueError("A recipe field is found by exactly one of a selector or a label.")
        return self


class RecipeButton(BaseModel):
    css: str = Field(max_length=300)
    text: str = Field("", max_length=120)
    action: Literal["next", "submit"]


class Recipe(BaseModel):
    host: str
    name: str = ""
    origin: Literal["taught", "ai"]
    approved: bool = False
    open: str = Selector  # the posting's link to the form
    fields: list[RecipeField] = Field(default_factory=list, max_length=300)
    buttons: list[RecipeButton] = Field(default_factory=list, max_length=40)
    receipt: str = Field("", max_length=200)  # the confirmation page's heading
    created_at: str = Field(default_factory=now)
    failures: int = 0

    @field_validator("host")
    @classmethod
    def plain_host(cls, host):
        if not HOST.fullmatch(host):
            raise ValueError("A recipe belongs to one plain https host name.")
        return host

    @property
    def id(self):
        return "recipe:" + self.host

    def merged(self, other):
        """This recipe plus the entries another draft for the same site learned (a repair, or a later page)."""
        seen = {(f.css, f.match) for f in other.fields}
        buttons = {(b.css, b.text) for b in other.buttons}
        return self.model_copy(update={
            "fields": [f for f in self.fields if (f.css, f.match) not in seen] + other.fields,
            "buttons": [b for b in self.buttons if (b.css, b.text) not in buttons] + other.buttons,
            "receipt": other.receipt or self.receipt, "open": other.open or self.open, "approved": False})


def recipes(store):
    return {host: Recipe.model_validate(value) for host, value in store.get("recipes", {}).items()}


def recipe_for(store, url, approved=True):
    found = recipes(store).get(site_key(url))
    return found if found and (found.approved or not approved) else None


def save_recipe(store, recipe):
    stored = store.get("recipes", {})
    stored[recipe.host] = recipe.model_dump()
    store.put("recipes", stored)


def form_field(captured):
    names = {f.name for f in dataclass_fields(FormField)}
    return FormField(**{k: v for k, v in captured.items() if k in names})


def same(value, expected):
    if isinstance(expected, bool) or isinstance(value, bool):
        return value == expected
    digits = lambda v: re.sub(r"\D", "", str(v))
    return normalized(str(value)) == normalized(str(expected)) or (len(digits(value)) >= 7 and digits(value) == digits(expected))


def matching_fact(field, value, profile):
    """The one profile fact whose value is exactly what you typed, or ''."""
    keys = [key for key in fact_catalog(profile) if (found := linked(field, profile, key).value) is not None and same(value, found)]
    return keys[0] if len(keys) == 1 else ""


def alias_label(fact):
    """A label the resolver already knows for a plain profile fact ('email' → 'email')."""
    match = FACT.fullmatch(fact)
    return "" if match[1] or match[4] else next((label for label, attr in ALIASES.items() if attr == match[3]), "")


def page_changed(before, after):
    # ponytail: a click "advanced" when the URL changed or most field labels did; a wizard that keeps its labels needs a section heading check.
    a, b = {f["label"] for f in before["fields"]}, {f["label"] for f in after["fields"]}
    return before["url"] != after["url"] or len(a ^ b) > max(len(a), len(b), 1) / 2


def entry(captured, label=""):
    """A recipe entry for a control the generic scanner can't fill or name by itself, else None."""
    widget = captured.get("widget", "native")
    if widget == "native" and not label:
        return None
    where = {"css": captured["css"]} if captured.get("css") else {"match": captured["label"]} if captured["label"] else None
    if not where:
        return None
    return RecipeField(**where, label=label, kind="combobox" if widget != "native" else "", widget=widget)


def answered_value(captured, profile):
    """What you chose in this control, or None when you left it. An upload counts when it is your profile's resume or cover letter."""
    value = captured.get("value")
    if captured["kind"] == "radio":
        return captured.get("option") if value is True else None
    if captured["kind"] == "file":
        return next((path for path in (profile.resume_path, profile.cover_letter_path) if path and value == Path(path).name), None)
    if captured["kind"] == "password" or captured.get("disabled") or value in ("", None):
        return None
    return value


def build_from_capture(host, captures, final, profile, run, answers):
    """Manual teach, without AI: the recipe your clicks imply and the answers you typed that the bank doesn't have yet.

    `captures` holds one observed page per button click (with `clicked`); `final` is the page when you finished."""
    pages = captures + [final]
    advances = [(page, pages[i + 1]) for i, page in enumerate(captures) if page.get("clicked") and page_changed(page, pages[i + 1])]
    submitted = bool(advances) and not final["fields"]  # Your last click left the form for a confirmation page.
    buttons = []
    for index, (page, _) in enumerate(advances):
        clicked = page["clicked"]
        action = "submit" if submitted and index == len(advances) - 1 else "next"
        button = RecipeButton(css=clicked["css"], text=clicked["text"][:120], action=action)
        if button not in buttons:
            buttons.append(button)
    entries, proposals, done = [], [], set()
    # Newest first, so each control keeps what you last left in it, including what you typed after your last click.
    for page in reversed(pages):
        for captured in page["fields"]:
            value = answered_value(captured, profile)
            if value is None or captured["key"] in done:
                continue
            done.add(captured["key"])
            field = form_field(captured)
            found = resolve(field, profile, run, answers)
            fact = "" if found.value is not None else matching_fact(field, value, profile)
            label = alias_label(fact) if fact and not captured["label"] else ""
            if (made := entry(captured, label)) and made not in entries:
                entries.append(made)
            if found.value is not None or label or not captured["label"]:
                continue  # The bank or profile already answers it (yours wins over what you typed today), or the label now does.
            question = question_for(field, profile)
            proposals.append(ApprovedAnswer(question=question, fact=fact, profile_name=run.profile_name, scope="global") if fact else
                             ApprovedAnswer(question=question, value=value, profile_name=run.profile_name, scope="employer", scope_key=employer_key(run.job_url)))
    receipt = next((h for h in final.get("headings", []) if h), "")[:200] if submitted else ""
    return Recipe(host=host, name=f"{host} (taught)", origin="taught", fields=entries, buttons=buttons, receipt=receipt), proposals


def build_from_trace(host, trace):
    """Self-teach: the entries the AI's working actions imply. `trace` is a list of {fields: [...], advance, submit}."""
    entries, buttons = [], []
    for page in trace:
        for captured, label, widget in page["fields"]:
            made = entry({**captured, "widget": widget}, label)
            if made and made not in entries:
                entries.append(made)
        for key, action in (("advance", "next"), ("submit", "submit")):
            if page.get(key):
                button = RecipeButton(css=page[key]["css"], text=page[key]["text"][:120], action=action)
                if button not in buttons:
                    buttons.append(button)
    return Recipe(host=host, name=f"{host} (AI)", origin="ai", fields=entries, buttons=buttons)
