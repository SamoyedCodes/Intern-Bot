import pytest

from core.automation.models import ats_name, canonical_url, employer_key, job_identity


@pytest.mark.parametrize('url', [
    'https://a.myworkdayjobs.com/job/1?step=2#apply',
    'https://jobs.polymer.co/example/1#apply',
    'https://workforcenow.adp.com/mascsr/default?jobId=12',
    'https://careers.example.test/?source=&ref=a%2Fb#apply',
    'https://careers.example.test/job/1',
])
def test_canonical_url_preserves_application_query_and_fragment(url):
    assert canonical_url(url) == url


@pytest.mark.parametrize('url', [
    'http://a.myworkdayjobs.com/job',
    'https://user:secret@a.myworkdayjobs.com/job',
    'https://a.myworkdayjobs.com:8080/job',
])
def test_canonical_url_rejects_plain_http_credentials_and_custom_ports(url):
    with pytest.raises(ValueError):
        canonical_url(url)


@pytest.mark.parametrize('first, second', [
    ('https://a.wd1.myworkdayjobs.com/en-US/job/Intern_R123', 'https://a.wd1.myworkdayjobs.com/job/Different_R123'),
    ('https://jobs.example.test/123', 'https://jobs.example.test/123?utm_source=mail&ref=feed'),
])
def test_job_identity_ignores_slugs_locales_and_tracking(first, second):
    assert job_identity(first) == job_identity(second)


@pytest.mark.parametrize('first, second', [
    ('https://workforcenow.adp.com/mascsr/default?jobId=12', 'https://workforcenow.adp.com/mascsr/default?jobId=13'),
    ('https://boards.greenhouse.io/embed/job_app?token=1', 'https://boards.greenhouse.io/embed/job_app?token=2'),
])
def test_job_identity_keeps_the_job_selecting_query(first, second):
    assert job_identity(first) != job_identity(second)


@pytest.mark.parametrize('url, name', [
    ('https://boards.greenhouse.io/example/jobs/1', 'Greenhouse'),
    ('https://jobs.lever.co/example/1', 'Lever'),
    ('https://jobs.ashbyhq.com/example/1', 'Ashby'),
    ('https://careers.example.test/job/1', ''),
    ('https://boards.greenhouse.io.evil.test/example/jobs/1', ''),
    ('https://jobs.lever.co.evil.test/example/1', ''),
    ('https://jobs.ashbyhq.com.evil.test/example/1', ''),
])
def test_ats_name_matches_exact_hosts_only(url, name):
    assert ats_name(canonical_url(url)) == name


@pytest.mark.parametrize('first, second', [
    ('https://workforcenow.adp.com/mascsr/default?cid=first&jobId=1', 'https://workforcenow.adp.com/mascsr/default?cid=second&jobId=1'),
    ('https://apply.workable.com/first/j/1', 'https://apply.workable.com/second/j/1'),
    ('https://recruiting.paylocity.com/Recruiting/Jobs/Details/1', 'https://recruiting.paylocity.com/Recruiting/Jobs/Details/2'),
    ('https://jobs.lever.co/example/1', 'https://jobs.lever.co/another-company/2'),
])
def test_shared_hosts_never_share_an_employer_key_across_tenants(first, second):
    assert employer_key(first) != employer_key(second)
