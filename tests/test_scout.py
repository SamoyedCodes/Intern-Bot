import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from core.automation.models import ApplicantProfile, ApplicationRun, Education
from core.scout import (
    SG, Assessment, Evidence, Scout, ScoutSettings, consent_key, daily_due, deadline_expired,
    json_reply, search_context, sort_key, verified_opportunity, write_log,
)
from core.scout_sources import EXCLUDED, PostingHTML, PublicReader, PublicRedirect, discover, employment_link, public_url
from core.storage.local_store import LocalStore

AT = datetime(2026, 11, 9, 8, tzinfo=SG)
PROFILE = ApplicantProfile(first_name='Ada', email='private@example.test', citizenship='Singapore',
                           education=[Education(degree='BSc', major='Data Science and Economics', current=True)])
CFG = {'provider': 'openai', 'name': 'OpenAI', 'model': 'gpt-6-luna', 'key': 'secret', 'url': '', 'local': False}
ROOT = 'https://employer.test/careers'
TEXT = 'Data internship at Example Finance. Apply now. Current undergraduates welcome. Posted 2026-11-08. Closes 2026-11-23.'


def assessment(**changes):
    values = dict(kind='internship', eligible=True, is_posting=True, is_open=True, is_publisher=True,
        title='Data internship', organisation='Example Finance', reason='Data analysis for a finance team.',
        evidence={'opening': Evidence(value='Open', quote='Apply now.'),
                  'eligibility': Evidence(value='Current undergraduates', quote='Current undergraduates welcome.'),
                  'published': Evidence(value='2026-11-08', quote='Posted 2026-11-08.'),
                  'deadline': Evidence(value='2026-11-23', quote='Closes 2026-11-23.')})
    values.update(changes)
    return Assessment(**values)


def opportunity(a=None, text=TEXT, at=AT, url='https://employer.test/jobs/intern-1', settings=None, name='Default'):
    return verified_opportunity(a or assessment(), url, text, name, PROFILE, settings or ScoutSettings(), at)


@pytest.mark.parametrize('mode,expected', [('internships', {'internship'}), ('jobs', {'job'}), ('both', {'internship', 'job'})])
def test_mixed_public_board_filters_types_graduate_jobs_and_scholarships(store, mode, expected):
    parser = PostingHTML(ROOT)
    parser.feed((Path(__file__).parent / 'fixtures/scout/board.html').read_text())
    pages = {ROOT: (ROOT, parser.text, parser.links)}
    replies = {ROOT: assessment(kind='other')}
    for index, link in enumerate(parser.links):
        title = ['Data internship', 'Student data assistant', 'Graduate economist', 'Scholarship'][index]
        kind = ['internship', 'job', 'job', 'other'][index]
        text = TEXT.replace('Data internship', title)
        pages[link] = (link, text, [])
        replies[link] = assessment(title=title, kind=kind, eligible=index != 2)
    reader = FakeReader(pages)
    scout = Scout(store, CFG, reader=reader, search=lambda *a: [],
                  assess=lambda cfg, mode, payload: replies[json.loads(payload)['url']].model_dump_json())
    report = scout.scan('Default', PROFILE, ScoutSettings(mode=mode, sources=ROOT), AT)
    items = store.opportunities('Default')
    assert {i.kind for i in items} == expected
    assert all(i.title not in {'Graduate economist', 'Scholarship'} for i in items)
    assert all(not i.evidence['hours'].value for i in items)
    assert report['status'] == 'complete' and reader.closed
    assert report['search_requests'] <= 6
    assert (store.path.parent / 'opportunities-log.md').exists()


def test_careers_hostname_does_not_make_feedback_and_documents_job_candidates():
    assert not employment_link('https://careerservices.smu.edu.sg/form/website-feedback')
    assert not employment_link('https://static.mycareersfuture.gov.sg/docs/mycareersfuture_sg_user_faqs.pdf')
    assert employment_link('https://jobs.eu.lever.co/sggc/id')
    assert employment_link('https://careers.sgx.com/job/finance-intern/123')
    assert EXCLUDED.search('https://www.smu.edu.sg/form/website-feedback')
    assert EXCLUDED.search('https://isomer-user-content.by.gov.sg/path/CCS_2026.pdf')


class FakeReader:
    def __init__(self, pages):
        self.pages, self.reads, self.closed = pages, [], False

    def read(self, url, listing=False):
        self.reads.append(url)
        result = self.pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def test_evidence_must_be_present_and_opening_is_mandatory():
    a = assessment()
    a.evidence['hours'] = Evidence(value='Part-time', quote='Part-time allowed')
    a.evidence['published'] = Evidence(value='2026-11-09', quote='Invented publication date')
    item = opportunity(a)
    assert item.freshness == 'undated' and not item.evidence['hours'].value
    a.evidence['opening'].quote = 'Not in the page'
    assert opportunity(a) is None
    assert opportunity(assessment(title='Invented role')) is None
    assert opportunity(assessment(is_publisher=False)) is None
    assert opportunity(assessment(is_open=False)) is None
    assert opportunity(assessment(eligible=False)) is None
    assert opportunity(assessment(is_posting=False)) is None


def test_unrelated_real_quotes_cannot_prove_dates_or_working_hours():
    a = assessment()
    a.evidence['hours'] = Evidence(value='Full-time', quote='Apply now.')
    a.evidence['published'] = Evidence(value='2026-11-09', quote='Current undergraduates welcome.')
    item = opportunity(a)
    assert item.freshness == 'undated' and not item.evidence['hours'].value


@pytest.mark.parametrize('age,freshness', [(timedelta(hours=48), 'recent'), (timedelta(hours=48, seconds=1), 'earlier'),
                                           (timedelta(days=60), 'earlier'), (timedelta(seconds=-1), None)])
def test_48_hour_boundary_uses_evidenced_posting_time(age, freshness):
    date = (AT - age).isoformat()
    a = assessment()
    a.evidence['published'] = Evidence(value=date, quote=date)
    item = opportunity(a, TEXT + date)
    assert (item and item.freshness) == freshness


def test_older_dated_postings_rank_between_recent_and_undated(window):
    for i, published in enumerate(('2026-11-08', '2026-10-01', '')):
        a = assessment(title=f'Data internship {i}', evidence={**assessment().evidence, 'deadline': Evidence(),
                       'published': Evidence(value=published, quote=f'Posted {published}.') if published else Evidence()})
        window.store.save_opportunity(opportunity(a, TEXT + f' Data internship {i}. Posted {published}.', url=f'https://employer.test/jobs/{i}'))
    view = window.scout_view
    view.history.setCurrentIndex(1)
    view.render()
    groups = [view.results.topLevelItem(i).text(0) for i in range(view.results.topLevelItemCount())]
    assert groups == ['Posted in the last 48 hours', 'Open · posted earlier', 'Open leads · date unverified']


def test_deadline_today_is_open_and_14_days_is_urgent():
    item = opportunity()
    assert sort_key(item, AT)[0] is False
    a = assessment()
    a.evidence['deadline'] = Evidence(value='2026-11-24', quote='2026-11-24')
    assert sort_key(opportunity(a, TEXT + '2026-11-24'), AT)[0] is True
    a.evidence['deadline'] = Evidence(value='2026-11-09', quote='2026-11-09')
    assert opportunity(a, TEXT + '2026-11-09')
    a.evidence['deadline'] = Evidence(value='2026-11-08', quote='2026-11-08')
    assert opportunity(a) is None
    assert deadline_expired('2026-11-09T07:59:59+08:00', AT)
    assert not deadline_expired('2026-11-09', AT)


def test_dedup_promotes_undated_keeps_first_seen_and_isolates_profiles(store):
    a = assessment()
    a.evidence.pop('published')
    first = opportunity(a, at=AT - timedelta(days=1))
    assert store.save_opportunity(first)
    assert not store.save_opportunity(opportunity(a, url=first.url + '?utm_source=search'))
    assert store.save_opportunity(opportunity())
    assert not store.save_opportunity(opportunity())
    assert not store.save_opportunity(opportunity(a))
    assert store.opportunities('Default')[0].freshness == 'recent'
    assert store.save_opportunity(opportunity(name='Second'))
    reloaded = LocalStore(store.path, store.vault)
    assert len(reloaded.opportunities('Default')) == 1
    assert reloaded.opportunities('Default')[0].first_seen == first.first_seen
    assert len(reloaded.opportunities()) == 2
    write_log(reloaded)
    assert (store.path.parent / 'opportunities-log.md').read_text().count('## ') == 2


def test_scan_is_bounded_and_partial_errors_preserve_results(store):
    links = [f'https://employer.test/jobs/{i}' for i in range(60)]
    pages = {ROOT: (ROOT, 'Careers', links), **{url: (url, TEXT, []) for url in links}}
    pages[links[0]] = ValueError('secret request context must not be logged')
    scout = Scout(store, CFG, reader=FakeReader(pages), search=lambda *a: [], assess=lambda *a: assessment().model_dump_json())
    report = scout.scan('Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert report['status'] == 'partial' and report['checked'] == 40
    assert len(store.opportunities()) == 39
    assert any('limit' in issue for issue in report['issues'])
    assert 'secret request' not in json.dumps(store.scout_reports('Default'))


def test_cancelled_scan_closes_reader(store):
    stop = Event()
    stop.set()
    reader = FakeReader({})
    report = Scout(store, CFG, stop=stop, reader=reader).scan('Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert report['status'] == 'cancelled' and report['checked'] == 0 and reader.closed


def test_search_failure_still_checks_direct_source(store):
    def fail(*args):
        raise ValueError('Web search unavailable')
    reader = FakeReader({ROOT: (ROOT, TEXT, [])})
    report = Scout(store, CFG, reader=reader, search=fail, assess=lambda *a: assessment().model_dump_json()).scan(
        'Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert report['status'] == 'partial' and len(store.opportunities()) == 1


def test_official_feed_metadata_is_available_only_after_opening_posting(store):
    board = 'https://jobs.eu.lever.co/example'
    feed = 'https://api.eu.lever.co/v0/postings/example?mode=json'
    url = board + '/id'
    reader = FakeReader({ROOT: (ROOT, 'Careers', [board]), feed: (feed, json.dumps([{'hostedUrl': url, 'text': 'Data internship'}]), []),
                         board: (board, 'Careers', []), url: (url, TEXT, [])})
    payloads = []
    def assess(cfg, mode, payload):
        payloads.append(json.loads(payload))
        return assessment().model_dump_json()
    Scout(store, CFG, reader=reader, search=lambda *a: [], assess=assess).scan('Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert url in reader.reads
    assert any('Official board feed' in p['page'] for p in payloads if p['url'] == url)
    assert len(store.opportunities()) == 1


def test_daily_schedule_catches_up_in_singapore_and_respects_attempt():
    settings = ScoutSettings(enabled=True)
    assert not daily_due(settings, None, AT - timedelta(seconds=1))
    assert daily_due(settings, None, AT)
    assert daily_due(settings, '2026-11-08', AT.astimezone(timezone.utc) + timedelta(hours=8))
    assert not daily_due(settings, '2026-11-09', AT + timedelta(hours=6))
    assert not daily_due(ScoutSettings(), None, AT)


def test_context_redacts_identity_and_consent_tracks_provider_profile_and_brief():
    settings = ScoutSettings(brief='Contact Ada at private@example.test. I want data internships.')
    context = search_context(settings, PROFILE)
    assert 'Ada' not in context and 'private@example.test' not in context and 'Singapore' in context
    token = consent_key(CFG, settings, PROFILE)
    assert token != consent_key({**CFG, 'provider': 'anthropic'}, settings, PROFILE)
    assert token != consent_key(CFG, settings, PROFILE.model_copy(update={'skills': 'Python'}))
    assert token != consent_key(CFG, settings.model_copy(update={'brief': 'Other roles'}), PROFILE)


def test_public_fetch_rejects_private_hosts_and_redirects(monkeypatch):
    monkeypatch.setattr('core.scout_sources.socket.getaddrinfo', lambda *a, **k: [(None, None, None, None, ('127.0.0.1', 443))])
    for url in ['http://employer.test', 'https://localhost/x', 'https://employer.test/']:
        with pytest.raises(ValueError):
            public_url(url)
    with pytest.raises(ValueError):
        PublicRedirect().redirect_request(None, None, 302, '', {}, 'https://employer.test/')


def test_native_search_uses_only_tool_urls_and_brave_key_is_a_header(monkeypatch):
    calls = []
    def api(url, body=None, headers=None):
        calls.append((url, body, headers))
        return {'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'text': 'https://invented.test/job'}]},
            {'type': 'web_search_call', 'action': {'sources': [{'url': 'https://official.test/job'}]}}]}
    monkeypatch.setattr('core.scout_sources.api_json', api)
    assert discover(CFG, 'Find data internships') == ['https://official.test/job']
    assert calls[0][1]['max_tool_calls'] == 1 and calls[0][1]['store'] is False
    assert calls[0][2] == {'Authorization': 'Bearer secret'}
    discover(CFG, 'Find data internships', 'brave-secret')
    assert 'brave-secret' not in calls[-1][0] and calls[-1][2]['X-Subscription-Token'] == 'brave-secret'


def test_claude_search_uses_bounded_tool_results(monkeypatch):
    import anthropic
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['max_retries'] == 0
            self.messages = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(stop_reason='max_tokens', content=[SimpleNamespace(type='web_search_tool_result',
                content=[SimpleNamespace(type='web_search_result', url='https://official.test/jobs/1')]),
                SimpleNamespace(type='web_search_tool_result', content=SimpleNamespace(error_code='max_uses_exceeded'))])
    monkeypatch.setattr(anthropic, 'Anthropic', Client)
    assert discover({**CFG, 'provider': 'anthropic'}, 'Find internships') == ['https://official.test/jobs/1']
    assert calls[0]['tools'][0]['max_uses'] == 1


def test_assessment_parser_accepts_an_explanation_around_a_valid_object():
    expected = assessment()
    assert json_reply('Posting assessment:\n```json\n' + expected.model_dump_json() + '\n```') == expected
    with pytest.raises(ValueError):
        json_reply('Unable to assess this page.')
    # Live Sonnet reply: a first object, then a self-correction. The correction is the answer.
    wrong = expected.model_copy(update={'eligible': False})
    reply = wrong.model_dump_json() + '\n\nCorrection: The correct output is:\n\n' + expected.model_dump_json() + '\n\nSee {the posting}.'
    assert json_reply(reply) == expected


def test_scout_application_handoff_queues_matched_profile_and_repeated_click_opens_existing(window, monkeypatch):
    view = window.tasks_view
    started = []
    monkeypatch.setattr(view.service, 'start', lambda run, profile, credential, **k: started.append(run) or True)
    active = ApplicationRun(job_url='https://employer.test/jobs/busy')
    view.add_task(active)
    view._active_id = active.id
    item = opportunity(name='Matched')
    window.prepare_opportunity(item)
    run = view.selected()
    assert run.profile_name == 'Matched' and run.profile_snapshot.first_name == 'Ada'
    assert run.id in view._queue and not started and window.stack.currentIndex() == 0
    window.prepare_opportunity(item)
    assert view.selected().id == run.id and view._queue == [run.id]
    view._active_id = None
    view._start_next()
    assert started[0].id == run.id and not started[0].approved_review and not started[0].submission_attempted


def test_scout_application_starts_when_idle(window, monkeypatch):
    started = []
    monkeypatch.setattr(window.tasks_view.service, 'start', lambda run, profile, credential, **k: started.append(run) or True)
    window.prepare_opportunity(opportunity())
    assert len(started) == 1 and not started[0].approved_review


def test_scout_scheduler_persists_catchup_and_does_not_overlap(window, monkeypatch):
    view = window.scout_view
    settings = ScoutSettings(enabled=True)
    settings.consent = consent_key(CFG, settings, window.store.profiles()['Default'])
    window.store.put('scout:Default', settings.model_dump())
    monkeypatch.setattr(view, 'configuration', lambda: CFG)
    workers = []
    class Worker:
        def __init__(self, *args):
            self.progress = self.completed = self.failed = self.finished = SimpleNamespace(connect=lambda *a: None)
            self.stop = Event()
            workers.append(self)
        def start(self):
            pass
    monkeypatch.setattr('gui.views.scout_view.ScoutWorker', Worker)
    view.check_daily(AT)
    view.check_daily(AT)
    assert len(workers) == 1 and window.store.get('scout-last-attempt:Default') == '2026-11-09'
    view.worker = None
    view.check_daily(AT)
    assert len(workers) == 1


def test_daily_scan_needs_current_provider_consent(window, monkeypatch):
    view = window.scout_view
    settings = ScoutSettings(enabled=True, consent='old-context')
    window.store.put('scout:Default', settings.model_dump())
    monkeypatch.setattr(view, 'configuration', lambda: CFG)
    view.check_daily(AT)
    assert view.worker is None and window.store.get('scout-last-attempt:Default') is None
    assert 'preview' in view.notice.text()
    assert not window.scout_badge.isHidden() and 'paused for Default' in window.nav_buttons[4].toolTip()
    view.notice.notify('')
    view.check_daily(AT + timedelta(seconds=30))
    assert view.notice.text() == ''  # warned once, not on every 30-second tick
    view.switch_profile('Default')  # load the enabled setting into the form, as opening Scout would
    view.daily.setChecked(False)
    assert window.scout_badge.isHidden()


def test_log_failure_keeps_database_results_and_reports_partial(store, monkeypatch):
    def fail(*a):
        raise OSError('disk unavailable')
    monkeypatch.setattr('core.scout.write_log', fail)
    report = Scout(store, CFG, reader=FakeReader({ROOT: (ROOT, TEXT, [])}), search=lambda *a: [],
                   assess=lambda *a: assessment().model_dump_json()).scan('Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert report['status'] == 'partial' and len(store.opportunities()) == 1
    assert 'Markdown log' in report['issues'][-1]


def test_scout_render_escapes_posting_html_and_keeps_hours_unknown(window):
    item = opportunity()
    item.reason = '<script>bad()</script>'
    window.store.save_opportunity(item)
    view = window.scout_view
    view.history.setCurrentIndex(1)
    row = view.results.topLevelItem(0).child(0)
    assert row.text(3) == 'Not stated'
    view.results.setCurrentItem(row)
    assert '<script>bad()</script>' in view.detail.toPlainText()
    assert view.prepare_btn.isEnabled()


def test_scout_shutdown_waits_asynchronously_for_worker(window):
    view = window.scout_view
    view.worker = SimpleNamespace(stop=Event())
    assert view.shutdown() is False
    assert view.worker.stop.is_set()
    view.worker = None
    assert view.shutdown() is True


def test_html_extraction_preserves_posting_schema_but_ignores_executable_script():
    parser = PostingHTML(ROOT)
    parser.feed('<h1>Data internship</h1><script>alert("secret")</script>'
                '<script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-11-08"}</script>'
                '<a href="/jobs/1">Apply now</a>')
    assert 'secret' not in parser.text and '2026-11-08' in parser.text
    assert parser.links == ['https://employer.test/jobs/1']


def test_json_feed_is_not_truncated_before_parsing(monkeypatch):
    import core.scout_sources as module
    payload = json.dumps([{'hostedUrl': 'https://jobs.lever.co/example/id', 'description': 'x' * 35000}]).encode()
    response = SimpleNamespace(url='https://api.lever.co/v0/postings/example?mode=json',
        headers=SimpleNamespace(get_content_type=lambda: 'application/json', get_content_charset=lambda: 'utf-8'),
        read=lambda n: payload)
    class Response:
        def __enter__(self):
            return response
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(module, 'public_url', lambda url: url)
    monkeypatch.setattr(module, 'build_opener', lambda *a: SimpleNamespace(open=lambda *a, **k: Response()))
    _, text, links = PublicReader().read(response.url)
    assert json.loads(text)[0]['hostedUrl'] == links[0] and len(text) > 28000


@pytest.mark.browser
def test_scout_prepare_button_fills_browser_reaches_review_and_reopens_existing(window, monkeypatch):
    import asyncio
    import time
    from playwright.async_api import Page
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from core.browser.playwright_mgr import AsyncPlaywrightManager
    import core.automation.service as service_module
    import gui.views.tasks_view as tasks_module

    url = 'https://boards.greenhouse.io/fixture/jobs/SCOUT_R1'
    fixture = (Path(__file__).parent / 'fixtures/speedyapply/greenhouse.html').read_text().replace('</form>',
        '<button type="button" id="submit_app" onclick="window.submissions++">Submit Application</button></form>'
        '<script>window.submissions=0</script>')
    requests = []
    original_goto = Page.goto

    async def intercepted_goto(page, destination, **kwargs):
        assert destination == url
        async def local_only(route):
            requests.append((route.request.method, route.request.url))
            if route.request.url == url and route.request.method == 'GET':
                await route.fulfill(status=200, content_type='text/html', body=fixture)
            else:
                await route.abort()
        await page.route('**/*', local_only)
        return await original_goto(page, destination, **kwargs)

    monkeypatch.setattr(Page, 'goto', intercepted_goto)
    monkeypatch.setattr(service_module, 'AsyncPlaywrightManager', lambda **kwargs: AsyncPlaywrightManager(**{**kwargs, 'headless': True}))
    monkeypatch.setattr(tasks_module, 'desktop_notification', lambda *a: None)
    item = opportunity(url=url)
    item.profile_snapshot = ApplicantProfile(first_name='Ada', last_name='Example', email='ada@example.test')
    window.store.save_opportunity(item)
    window._select_nav(4)
    scout_view = window.scout_view
    scout_view.history.setCurrentIndex(1)
    window.show()
    app = QApplication.instance()
    app.processEvents()
    assert scout_view.selected().id == item.id
    QTest.mouseClick(scout_view.prepare_btn, Qt.LeftButton)
    view = window.tasks_view
    deadline = time.monotonic() + 30
    while (view.service.busy or view._active_id) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert not view.service.busy and not view._active_id
    assert window.stack.currentIndex() == 0
    assert len(view.tasks) == 1
    run = view.tasks[0]
    assert run.status == 'ready_for_review', [(i.kind, i.message) for i in run.interventions]
    assert all(f.disposition == 'verified' for f in run.fields.values())
    assert not run.submission_attempted and not run.approved_review
    assert window.store.get_run(run.id).status == 'ready_for_review'

    async def inspect_form():
        page = view.service.sessions[run.id][1].page
        assert await page.locator('#first_name').input_value() == 'Ada'
        assert await page.locator('#last_name').input_value() == 'Example'
        assert await page.locator('#email').input_value() == 'ada@example.test'
        assert await page.evaluate('window.submissions') == 0
    asyncio.run_coroutine_threadsafe(inspect_form(), view.service.loop).result(timeout=10)
    assert requests == [('GET', url)]
    window._select_nav(4)
    app.processEvents()
    QTest.mouseClick(scout_view.prepare_btn, Qt.LeftButton)
    assert window.stack.currentIndex() == 0 and len(view.tasks) == 1
    assert view.selected().id == run.id and requests == [('GET', url)]


def test_stress_cases_nulls_ordinals_intern_words_and_search_wording(store):
    reply = assessment().model_dump()
    reply.update(official_url=None, evidence={**reply['evidence'], 'start': None, 'hours': {'value': None, 'quote': None}})
    assert json_reply(json.dumps(reply)).evidence['hours'] == Evidence()
    a = assessment(evidence={**assessment().evidence, 'deadline': Evidence(value='2026-11-23', quote='Closes 23rd November 2026.')})
    assert opportunity(a, TEXT + ' Closes 23rd November 2026.').deadline == '2026-11-23'
    assert not employment_link('https://employer.test/news/internet-banking')
    assert not employment_link('https://employer.test/international-relations')
    queries = []
    Scout(store, {**CFG, 'provider': 'anthropic', 'name': 'Claude'}, reader=FakeReader({ROOT: (ROOT, 'Careers', [])}),
          search=lambda cfg, q, key: queries.append(q) or [], assess=lambda *a: '').scan('Default', PROFILE, ScoutSettings(sources=ROOT, mode='both'), AT)
    assert queries and all('internships and student-eligible jobs' in q for q in queries)


def test_tab_switch_keeps_unsaved_search_brief(window):
    view = window.scout_view
    view.brief.setPlainText('Unsaved brief')
    view.hide()
    view.show()
    assert view.brief.toPlainText() == 'Unsaved brief'


def test_non_employer_hosts_and_client_rendered_boards(store, monkeypatch):
    links = ['https://www.glassdoor.sg/Job/x', 'https://sg.linkedin.com/company/x', 'https://www.straitstimes.com/jobs/x',
             'https://form.gov.sg/abc', 'https://www.lever.co/job-seeker-support', 'https://jobs.lever.co/acme/1']
    reader = FakeReader({ROOT: (ROOT, 'Careers', links), links[-1]: (links[-1], TEXT, [])})
    Scout(store, CFG, reader=reader, search=lambda *a: [], assess=lambda *a: assessment().model_dump_json()).scan(
        'Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert [u for u in reader.reads if u != ROOT and 'api.lever.co' not in u] == [links[-1]]
    monkeypatch.setattr('core.scout_sources.public_url', lambda url: url)
    monkeypatch.setattr(PublicReader, 'render', lambda self, url: ('rendered', url, []))
    assert PublicReader().read('https://jobs.careers.gov.sg/?q=intern')[0] == 'rendered'


def test_in_page_anchors_do_not_requeue_a_checked_page(store):
    page = 'https://employer.test/jobs/intern-1'
    reader = FakeReader({ROOT: (ROOT, 'Careers', [page, page + '#main-content', 'https://employer.test/jobs#/job/2', 'https://employer.test/blog/intern-tips']),
                         page: (page, TEXT, []), 'https://employer.test/jobs#/job/2': ('https://employer.test/jobs#/job/2', TEXT, [])})
    Scout(store, CFG, reader=reader, search=lambda *a: [], assess=lambda *a: assessment().model_dump_json()).scan(
        'Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert reader.reads[1:] == [page, 'https://employer.test/jobs#/job/2']



def test_sources_accept_bare_hosts_and_comments_but_refuse_http():
    from core.scout import source_rows
    rows = source_rows(ScoutSettings(sources='# Finance\nMAS | www.mas.gov.sg/careers\nemployer.test/jobs'))
    assert rows == [('MAS', 'https://www.mas.gov.sg/careers'), ('employer.test', 'https://employer.test/jobs')]
    with pytest.raises(ValueError):
        source_rows(ScoutSettings(sources='http://employer.test/jobs'))


def test_lever_epoch_date_is_readable_even_when_the_feed_entry_is_truncated(store):
    board = 'https://jobs.eu.lever.co/example'
    feed = 'https://api.eu.lever.co/v0/postings/example?mode=json'
    url = board + '/id'
    job = {'hostedUrl': url, 'text': 'Data internship', 'descriptionPlain': 'x' * 20000,
           'createdAt': int(datetime(2026, 11, 8, 9, 30, tzinfo=SG).timestamp() * 1000)}
    reader = FakeReader({ROOT: (ROOT, 'Careers', [board]), feed: (feed, json.dumps([job]), []), board: (board, 'Careers', []), url: (url, TEXT, [])})
    pages = []
    Scout(store, CFG, reader=reader, search=lambda *a: [], assess=lambda c, m, p: pages.append(json.loads(p)) or assessment().model_dump_json()).scan(
        'Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert any('"createdAt_date": "2026-11-08T09:30+08:00"' in p['page'] for p in pages if p['url'] == url)
    # The stored description is the posting itself, not the feed dump, and Prepare application hands it over.
    assert store.opportunities()[0].description == TEXT


def test_latest_scan_keeps_still_open_finds_and_marks_first_sightings(window):
    store, page = window.store, 'https://employer.test/jobs/intern-1'
    for _ in range(2):
        report = Scout(store, CFG, reader=FakeReader({ROOT: (ROOT, 'Careers', [page]), page: (page, TEXT, [])}), search=lambda *a: [],
                       assess=lambda *a: assessment().model_dump_json()).scan('Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert report['new_ids'] == [] and len(report['seen_ids']) == 1
    view = window.scout_view
    view.history.setCurrentIndex(0)
    view.render()
    assert view.results.topLevelItem(0).child(0).text(0) == 'Data internship'


def test_prepare_application_uses_posting_text(window, monkeypatch):
    started = []
    monkeypatch.setattr(window.tasks_view.service, 'start', lambda run, profile, credential, **k: started.append(run) or True)
    window.prepare_opportunity(opportunity())
    assert started[0].job_description == TEXT


def test_claude_search_falls_back_to_basic_tool_for_older_models(monkeypatch):
    import anthropic, httpx2
    tools = []
    class Client:
        def __init__(self, **kwargs):
            self.messages = self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def create(self, **kwargs):
            tools.append(kwargs['tools'][0]['type'])
            if kwargs['tools'][0]['type'] == 'web_search_20260209':
                raise anthropic.BadRequestError('unsupported tool', response=httpx2.Response(400, request=httpx2.Request('POST', 'https://api.test')), body=None)
            return SimpleNamespace(content=[SimpleNamespace(type='web_search_tool_result',
                content=[SimpleNamespace(type='web_search_result', url='https://official.test/jobs/1')])])
    monkeypatch.setattr(anthropic, 'Anthropic', Client)
    assert discover({**CFG, 'provider': 'anthropic'}, 'Find internships') == ['https://official.test/jobs/1']
    assert tools == ['web_search_20260209', 'web_search_20250305']



def test_feed_postings_are_checked_before_landing_pages_on_many_hosts(store):
    board = 'https://jobs.eu.lever.co/example'
    feed = 'https://api.eu.lever.co/v0/postings/example?mode=json'
    postings = [f'{board}/{i}' for i in range(5)]
    landings = [f'https://host{i}.test/careers' for i in range(45)]
    pages = {ROOT: (ROOT, 'Careers', [board, *landings]), board: (board, 'Careers', []),
             feed: (feed, json.dumps([{'hostedUrl': u, 'text': 'Data internship'} for u in postings]), []),
             **{u: (u, TEXT, []) for u in postings + landings}}
    reader = FakeReader(pages)
    Scout(store, CFG, reader=reader, search=lambda *a: [], assess=lambda *a: assessment().model_dump_json()).scan(
        'Default', PROFILE, ScoutSettings(sources=ROOT), AT)
    assert all(u in reader.reads for u in postings)
