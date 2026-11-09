"""Site recipes: the format, manual-teach mapping, the recipe adapter in the real extension, and self-teach with a stubbed AI."""
import pytest
from pydantic import ValidationError

import core.automation.self_teach as self_teach
from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.models import ApplicationRun
from core.automation.recipes import Recipe, RecipeButton, RecipeField, build_from_capture, recipe_for, save_recipe
from core.automation.review import review_values
from core.automation.self_teach import SelfTeacher
from tests.support import open_fixture, profile_for

URL = "https://careers.niche.test/apply/123"
HOST = "careers.niche.test"
# A label-less phone input, a custom ARIA dropdown that shows its choice beside an emptied search input, and a "Finish" button.
FORM = """<form onsubmit="return false">
<input id=mob name=mob>
<label for=country>Country</label>
<div class=box><span class=shown></span><input id=country role=combobox aria-controls=list autocomplete=off required></div>
<ul id=list role=listbox hidden></ul>
<button type=button id=go onclick="window.submissions=(window.submissions||0)+1;document.body.innerHTML='<h1>Thanks, we got it</h1>'">{button}</button>
</form>
<script>
const opts=['Singapore','Malaysia','Indonesia'], input=document.getElementById('country'), list=document.getElementById('list'), shown=document.querySelector('.shown');
function render(){{list.innerHTML='';for(const o of opts.filter(o=>o.toLowerCase().includes(input.value.toLowerCase()))){{const li=document.createElement('li');
li.setAttribute('role','option');li.textContent=o;li.onclick=()=>{{shown.textContent=o;input.value='';list.hidden=true;}};list.appendChild(li);}}list.hidden=false;}}
input.addEventListener('mousedown',render);input.addEventListener('input',render);
</script>"""
TAUGHT = Recipe(host=HOST, origin="taught", approved=True, receipt="Thanks, we got it",
                fields=[RecipeField(css="#mob", label="Phone"), RecipeField(match="Country", kind="combobox", widget="aria-combobox")],
                buttons=[RecipeButton(css="#go", text="Finish", action="submit")])


def profile():
    return profile_for("greenhouse").model_copy(update={"country": "Singapore"})


@pytest.mark.parametrize("bad", [
    dict(host="evil.test/x", origin="taught"),
    dict(host=HOST, origin="taught", fields=[{"css": "#a", "match": "A"}]),
    dict(host=HOST, origin="taught", fields=[{"css": "#a", "widget": "eval"}]),
    dict(host=HOST, origin="robot"),
], ids=["host-with-path", "two-locators", "unknown-widget", "unknown-origin"])
def test_a_recipe_rejects_anything_outside_its_closed_format(bad):
    with pytest.raises(ValidationError):
        Recipe(**bad)


def captured(label, value, kind="text", css="", widget="native", key=None, **extra):
    return dict(key=key or label.lower(), label=label, selector="", kind=kind, value=value, options=[], option="", group="", row=0,
                css=css, widget=widget, named=False, **extra)


def test_manual_teach_keeps_no_values_and_proposes_only_what_the_bank_lacks():
    run, me = ApplicationRun(job_url=URL), profile()
    page1 = {"url": URL, "fields": [captured("First Name", "Ada"), captured("Contact e-mail", "ada@example.test"),
                                    captured("Favourite colour", "Blue"), captured("", "5551234567", css="#mob", key="mob"),
                                    captured("Country", "Singapore", kind="combobox", css="#country", widget="aria-combobox")],
             "buttons": [], "headings": [], "clicked": {"id": "b0", "text": "Next", "css": "#next", "kind": "next"}}
    page2 = {"url": URL + "/step2", "fields": [captured("Why us?", "")], "buttons": [], "headings": [],
             "clicked": {"id": "b0", "text": "Finish", "css": "#go", "kind": ""}}
    final = {"url": URL + "/done", "fields": [], "buttons": [], "headings": ["Thanks, we got it"]}
    recipe, proposals = build_from_capture(HOST, [page1, page2], final, me, run, [])
    assert [(b.css, b.action) for b in recipe.buttons] == [("#next", "next"), ("#go", "submit")]
    assert recipe.receipt == "Thanks, we got it"
    assert RecipeField(css="#mob", label="phone") in recipe.fields  # the unlabelled control is named after the profile fact it held
    assert RecipeField(css="#country", kind="combobox", widget="aria-combobox") in recipe.fields
    assert "ada@example.test" not in recipe.model_dump_json() and "Blue" not in recipe.model_dump_json()
    by_question = {a.question: a for a in proposals}
    assert set(by_question) == {"Contact e-mail", "Favourite colour"}  # First Name and Country already resolve from the profile
    assert by_question["Contact e-mail"].fact == "email" and by_question["Contact e-mail"].scope == "global"
    assert by_question["Favourite colour"].value == "Blue" and by_question["Favourite colour"].scope == "employer"


def test_a_click_that_stays_on_the_page_is_not_a_step():
    run = ApplicationRun(job_url=URL)
    page = {"url": URL, "fields": [captured("Favourite colour", "Blue")], "buttons": [], "headings": [],
            "clicked": {"id": "b1", "text": "Add another", "css": "#add", "kind": ""}}
    recipe, _ = build_from_capture(HOST, [page], {**page, "headings": []}, profile(), run, [])
    assert recipe.buttons == [] and recipe.receipt == ""


async def test_no_adapter_and_no_recipe_hands_off(context, store):
    page = await open_fixture(context, "", FORM.format(button="Finish"), URL)
    run = await ApplicationEngine(store).start(ApplicationRun(job_url=URL), profile(), ExtensionBridge(page, "r0"))
    assert run.interventions[0].message.startswith("No supported application form")


async def test_a_taught_recipe_fills_custom_controls_and_confirms_its_own_receipt(context, store):
    save_recipe(store, TAUGHT)
    page = await open_fixture(context, "", FORM.format(button="Finish"), URL)
    run = ApplicationRun(job_url=URL)
    run = await ApplicationEngine(store).start(run, profile(), ExtensionBridge(page, run.id))
    assert run.status == "ready_for_review" and not run.interventions, run.interventions
    assert {a.label: a.value for a in run.fields.values()} == {"Phone": "5551234567", "Country": "Singapore"}
    assert not await page.evaluate("Boolean(window.submissions)")  # "Finish" counts as Submit only through the recipe, and only after approval.
    run.approved_review = review_values(run)
    run = await ApplicationEngine(store).start(run, profile(), ExtensionBridge(page, run.id))
    assert run.submission_confirmed, run.interventions
    assert await page.evaluate("window.submissions") == 1


async def test_a_recipe_without_a_receipt_never_sends(context, store):
    save_recipe(store, TAUGHT.model_copy(update={"receipt": ""}))
    page = await open_fixture(context, "", FORM.format(button="Finish"), URL)
    run = ApplicationRun(job_url=URL)
    run = await ApplicationEngine(store).start(run, profile(), ExtensionBridge(page, run.id))
    run.approved_review = review_values(run)
    run = await ApplicationEngine(store).start(run, profile(), ExtensionBridge(page, run.id))
    assert not run.submission_attempted and "confirmation page" in run.interventions[0].message
    assert not await page.evaluate("Boolean(window.submissions)")


async def test_an_unapproved_recipe_is_not_used(context, store):
    save_recipe(store, TAUGHT.model_copy(update={"approved": False}))
    page = await open_fixture(context, "", FORM.format(button="Finish"), URL)
    run = await ApplicationEngine(store).start(ApplicationRun(job_url=URL), profile(), ExtensionBridge(page, "r1"))
    assert run.interventions[0].message.startswith("No supported application form")


STUB = {"name": "Stub", "local": True, "facts": False}
# Page 1 continues with "Proceed" to page 2, whose only way on is a real submission.
WIZARD = FORM.format(button="Proceed").replace(
    """onclick="window.submissions=(window.submissions||0)+1;document.body.innerHTML='<h1>Thanks, we got it</h1>'\"""",
    """onclick="document.querySelector('form').innerHTML='<label>Favourite colour<input id=colour required></label><button type=button id=send onclick=&quot;window.submissions=1&quot;>Submit application</button>'\"""")


def stub_ai(monkeypatch, plans):
    calls = []
    def generate_text(cfg, mode, context, max_tokens=4096):
        assert mode == "self_teach" and "5551234567" not in context and "ada@example.test" not in context  # never the values
        calls.append(context)
        return next(plan for marker, plan in plans if marker in context)
    monkeypatch.setattr(self_teach, "generate_text", generate_text)
    return calls


async def test_self_teach_fills_up_to_review_and_drafts_a_recipe(context, store, monkeypatch):
    calls = stub_ai(monkeypatch, [
        ("Proceed", '{"fields": {"f1": {"widget": "native", "label": "Phone"}, "f2": {"widget": "aria-combobox"}}, "advance": "b0"}'),
        ("Submit application", '{"fields": {}, "done": "review"}'),
    ])
    store.put("self_teach_consent", [HOST])
    page = await open_fixture(context, "", WIZARD, URL)
    run = await SelfTeacher(store).start(ApplicationRun(job_url=URL), profile(), page, STUB)
    # Page 2 asks something nobody answered, so it stops for you before the review.
    assert [i.question for i in run.interventions] == ["Favourite colour"], run.interventions
    draft = recipe_for(store, URL, approved=False)
    assert not draft.approved and draft.origin == "ai"
    assert RecipeField(css="#mob", label="Phone") in draft.fields
    assert any(f.widget == "aria-combobox" for f in draft.fields)
    assert [(b.css, b.action) for b in draft.buttons] == [("#go", "next")]
    assert len(calls) == 2 and run.ai_requests == 2
    assert not await page.evaluate("Boolean(window.submissions)")


async def test_self_teach_never_clicks_a_submission(context, store, monkeypatch):
    stub_ai(monkeypatch, [("Submit application", '{"fields": {}, "advance": "b0"}')])
    page = await open_fixture(context, "", FORM.format(button="Submit application"), URL)
    run = await SelfTeacher(store).start(ApplicationRun(job_url=URL), profile(), page, STUB)
    assert "review page" in run.interventions[0].message
    assert not await page.evaluate("Boolean(window.submissions)")
    assert [(b.text, b.action) for b in recipe_for(store, URL, approved=False).buttons] == [("Submit application", "submit")]


# FormSG (Chakra) markup: the question is the group's own label beside a radiogroup, and a chosen file replaces its input.
CHAKRA = """<form><div role=group><label>13.Open to other projects?</label><div role=radiogroup>
<label><input type=radio name=q13 value=Yes>Yes</label><label><input type=radio name=q13 value=No>No</label></div></div>
<div role=group><label>16.Where did you hear of us?</label><label><input type=checkbox name=src required aria-label="LinkedIn">LinkedIn</label>
<label><input type=checkbox name=src required aria-label="Website">Website</label></div>
<div role=group><label for=cv>5.Upload your resume</label><input type=file id=cv onchange="this.replaceWith(Object.assign(document.createElement('span'),{textContent:this.files[0].name}))"></div>
<button type=button id=nav>Navigate</button></form>"""


async def test_teach_reads_group_questions_and_an_upload_the_site_swaps_out(context, store, tmp_path):
    from core.automation.recipes import OBSERVE, TEACH
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    me, run = profile().model_copy(update={"resume_path": str(resume)}), ApplicationRun(job_url=URL)
    page = await open_fixture(context, "", CHAKRA, URL)
    captures = []
    await page.expose_binding("internTeach", lambda source, observed: captures.append(observed))
    await page.evaluate(TEACH)
    await page.check("input[value=Yes]")
    await page.check("input[aria-label=LinkedIn]")
    await page.set_input_files("#cv", str(resume))
    await page.click("#nav")
    labels = {f["label"] for f in captures[-1]["fields"]}
    assert {"13.Open to other projects?", "16.Where did you hear of us? — LinkedIn"} <= labels
    website = next(f for f in captures[-1]["fields"] if f["label"].endswith("Website"))
    assert not website["invalid"]  # one ticked box satisfies the required group
    _, proposals = build_from_capture(HOST, captures, await page.evaluate(OBSERVE), me, run, [])
    by_question = {a.question: a.value for a in proposals}
    assert by_question["5.Upload your resume"] == str(resume)
    assert by_question["13.Open to other projects?"] == "Yes"


async def test_self_teach_ticks_a_radio_hidden_behind_its_label(context, store, monkeypatch):
    from core.automation.models import ApprovedAnswer
    stub_ai(monkeypatch, [("Open", '{"fields": {}, "done": "review"}')])
    store.save_answer(ApprovedAnswer(question="13.Open to other projects?", value="Yes", scope="global"))
    hidden = """<form><div role=group><label>13.Open to other projects?</label><div role=radiogroup>
<label style="position:relative;display:inline-block;padding:8px"><input type=radio name=q13 value=Yes style="position:absolute;opacity:0;width:1px;height:1px;pointer-events:none"><span style="position:absolute;inset:0"></span>Yes</label>
<label style="position:relative;display:inline-block;padding:8px"><input type=radio name=q13 value=No style="position:absolute;opacity:0;width:1px;height:1px;pointer-events:none"><span style="position:absolute;inset:0"></span>No</label></div></div>
<button type=button>Submit application</button></form>"""
    page = await open_fixture(context, "", hidden, URL)
    await SelfTeacher(store).start(ApplicationRun(job_url=URL), profile(), page, STUB)
    assert await page.evaluate("document.querySelector('input[value=Yes]').checked")


async def test_self_teach_uploads_the_resume_and_asks_a_radio_question_once(context, store, monkeypatch, tmp_path):
    stub_ai(monkeypatch, [("Pick one", '{"fields": {}, "done": "review"}')])
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4")
    form = """<form><label for=cv>5.Upload your resume</label><input type=file id=cv>
<fieldset><legend>Pick one</legend><label><input type=radio name=r value=A required>A</label><label><input type=radio name=r value=B required>B</label></fieldset>
<button type=button>Submit application</button></form>"""
    page = await open_fixture(context, "", form, URL)
    run = await SelfTeacher(store).start(ApplicationRun(job_url=URL), profile().model_copy(update={"resume_path": str(resume)}), page, STUB)
    assert await page.evaluate("document.querySelector('#cv').files[0]?.name") == "resume.pdf"
    assert [i.question for i in run.interventions] == ["Pick one"]


# Lever markup: custom questions keep their text in .application-label, beside bare radios and an unlabelled input.
LEVER = """<meta charset=utf-8><form><ul><li class="application-question resume"><label><div class="application-label">Resume/CV <span>✱</span></div>
<div class="application-field"><a><span class="default-label">ATTACH RESUME/CV</span><input type=file name=resume></a>
<span class="resume-upload-failure">Couldn't auto-read resume.</span></div></label></li>
<li class="application-question custom-question"><div class="application-label"><div class="text">Highest degree?<span>✱</span></div></div>
<ul><li><label><input type=radio name="cards[a][field0]" value=Bachelor required><span>Bachelor</span></label></li></ul></li>
<li class="application-question custom-question"><div class="application-label"><div class="text">Graduation date?<span>✱</span></div></div>
<div class="application-field"><input class="card-field-input" name="cards[a][field1]" required></div></li></ul></form>"""


async def test_scan_names_lever_questions_by_their_question_text(context):
    from core.automation.recipes import SCAN
    page = await open_fixture(context, "", LEVER, URL)
    labels = [f["label"] for f in await page.evaluate(f"({SCAN})(null)")]
    assert labels == ["Resume/CV ✱", "Highest degree?", "Graduation date?"]


# Ashby markup: labels point at field entries, a yes/no question is two pressed-state buttons, and a side pane offers résumé autofill.
ASHBY = """<form><div class="_autofillPane_x"><input type=file></div>
<div data-field-path=loc><label for=loc>Location</label><div><input role=combobox aria-haspopup=listbox></div></div>
<div data-field-path=yn><label for=yn>Can you commit to 6 months?</label><div><button type=button aria-pressed=true>Yes</button><button type=button aria-pressed=false>No</button></div></div>
<fieldset><label for=x>Are you a citizen?</label><span><input type=radio name=c id=c0></span><label for=c0>Citizen</label>
<span><input type=radio name=c id=c1></span><label for=c1>Permanent resident</label></fieldset></form>"""


async def test_scan_reads_ashby_field_entries_and_yes_no_buttons(context):
    from core.automation.recipes import SCAN
    page = await open_fixture(context, "", ASHBY, URL)
    fields = [(f["label"], f["kind"], f["option"], f["value"], f["options"]) for f in await page.evaluate(f"({SCAN})(null)")]
    assert [f[:4] for f in fields] == [("Location", "combobox", "", ""), ("Can you commit to 6 months?", "radio", "Yes", True),
                      ("Can you commit to 6 months?", "radio", "No", False), ("Are you a citizen?", "radio", "Citizen", False),
                      ("Are you a citizen?", "radio", "Permanent resident", False)]
    # Every radio offers its question's choices, so the answer dialog lists them instead of asking for text.
    assert [f[4] for f in fields] == [[], ["Yes", "No"], ["Yes", "No"], ["Citizen", "Permanent resident"], ["Citizen", "Permanent resident"]]


# Greenhouse's react-select: the choice shows beside a search input, next to a hidden required input.
def react_select(id, label, shown, typed=''):
    choice = f'<div class="x-singleValue">{shown}</div>' if shown else '<div class="x-placeholder">Select...</div>'
    hidden = '' if shown else '<input required tabindex="-1" aria-hidden="true" value="">'
    return (f'<label id={id}-label for={id}>{label}</label><div class="x-control"><div class="x-valueContainer">{choice}'
            f'<div data-value="{typed}"><input id={id} role=combobox aria-labelledby={id}-label value="{typed}"></div></div></div>{hidden}')


async def test_scan_reads_react_select_choices_and_skips_their_hidden_inputs(context):
    from core.automation.recipes import SCAN
    page = await open_fixture(context, "", "<form>" + react_select("g", "GDPR Notice", "", "Yes") + react_select("c", "Country", "Singapore") + "</form>", URL)
    fields = [(f["label"], f["kind"], f["value"]) for f in await page.evaluate(f"({SCAN})(null)")]
    assert fields == [("GDPR Notice", "combobox", ""), ("Country", "combobox", "Singapore")]
