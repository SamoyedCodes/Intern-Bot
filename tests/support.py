"""Plain test helpers shared by several test modules; fixtures live in conftest.py."""
import asyncio
import json
import time
from pathlib import Path

from core.automation.engine import ApplicationEngine
from core.automation.extension_bridge import ExtensionBridge
from core.automation.fields import FormField
from core.automation.models import ApplicantProfile, ApplicationRun, Experience
from core.automation.speedy_profile import translate

FIXTURES = Path(__file__).parent / 'fixtures' / 'speedyapply'
URLS = json.loads((FIXTURES / 'urls.json').read_text())
EXTENSION = Path(__file__).parents[1] / 'extension'


class MemoryKeychain:
    """Stands in for the OS keychain backend."""
    def __init__(self):
        self.values = {}

    def set_password(self, service, key, value):
        self.values[(service, key)] = value

    def get_password(self, service, key):
        return self.values.get((service, key))


async def until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, 'Condition was not met in time'
        await asyncio.sleep(.05)


def profile_for(site):
    return ApplicantProfile(first_name='Ada', last_name='Example', email='ada@example.test', phone='5551234567',
        address_line1='123 Fictional St', city='Example City', postal_code='12345',
        experience=[Experience(job_title='Engineer', employer='Fictional Co', description='Built examples', start_date='2025-01')] if site == 'seek' else [])


def greenhouse(button=True, extra='', handler="window.submissions=(window.submissions||0)+1;document.body.innerHTML='<h1>Application submitted</h1>'"):
    """The Greenhouse fixture with optional extra fields and a submit button that counts clicks."""
    body = (FIXTURES / 'greenhouse.html').read_text()
    submit = f'<button type="button" id="submit_app" onclick="{handler}">Submit Application</button>' if button else ''
    return body.replace('</form>', extra + submit + '</form>')


def resume_upload(accept=None):
    """A Greenhouse resume control that shows an upload receipt like the real one."""
    accept = f' accept="{accept}"' if accept else ''
    return f'''<div id="s3_upload_for_resume"><label>Resume<input type=file{accept} onchange="this.closest('#s3_upload_for_resume').querySelector('[role=status]').textContent=this.files[0].name+' uploaded'"></label><span role=status></span></div>'''


def account_pages(start, after):
    """A Workday sign-in/create-account flow that shows `start` first and `after` once Create Account is clicked."""
    email = '<label>Email Address<input type=text data-automation-id=email></label><label>Password<input type=password data-automation-id=password></label>'
    create = email + '<label>Verify New Password<input type=password data-automation-id=verifyPassword></label><label><input type=checkbox data-automation-id=createAccountCheckbox>I agree to the terms</label><button type=button data-automation-id=signInLink onclick="show(`signin`)">Sign In</button><button type=button data-automation-id=createAccountSubmitButton onclick="created()">Create Account</button>'
    pages = {
        'signin': email + '<button type=button data-automation-id=createAccountLink onclick="show(`create`)">Create Account</button><button type=button data-automation-id=signInSubmitButton onclick="window.logins=(window.logins||0)+1">Sign In</button>',
        'create': create,
        'error': create + '<div data-automation-id=inputError>An account with this email already exists.</div>',
        'form': '<label>Preferred Name<input></label>',
    }
    return f'''<div id=root></div><script>
const pages={json.dumps(pages)};
function show(name){{document.getElementById('root').innerHTML=pages[name];}}
function created(){{window.creates=(window.creates||0)+1;const q=s=>document.querySelector(`[data-automation-id=${{s}}]`);
window.created=[q('email').value,q('password').value,q('verifyPassword').value,q('createAccountCheckbox').checked];show('{after}');}}
show('{start}');</script>'''


async def open_fixture(context, site, html=None, url=None):
    """Open the site's URL with every request answered locally by its fixture (or `html`)."""
    page = await context.new_page()
    body = html if html is not None else (FIXTURES / f'{site}.html').read_text()
    await page.route('**/*', lambda route: route.fulfill(body=body, content_type='text/html'))
    await page.goto(url or URLS[site])
    return page


async def prepare(page, store, site, profile=None, run=None):
    """Discover and authorize the site's adapter without starting it."""
    profile = profile or profile_for(site)
    run = run or ApplicationRun(job_url=page.url, auto_advance=False)
    bridge = ExtensionBridge(page, run.id)
    engine = ApplicationEngine(store)
    engine.bridge = bridge
    found = await bridge.discover()
    assert len(found['matches']) == 1, found
    assert found['matches'][0]['adapter']['id'] == site
    config = translate(profile, run, store.answers())
    config['adapter'] = site
    # These fixtures represent sites which already display a resume receipt.
    config['profile']['resumeData'] = {'fileName': 'fixture.pdf'}
    result = await bridge.command('prepare', config, binding=found['matches'][0])
    await engine.authorize(run, profile, [FormField(**f) for f in result['fields']])
    return bridge, engine, run, profile, config
