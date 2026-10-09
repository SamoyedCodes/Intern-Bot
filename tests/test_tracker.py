import csv

import pytest

from core.automation.models import ApplicationRun
from core.tracker import activity, export_csv, import_csv

HEADER = 'Company,Title,URL,Date\n'
ROW = 'Example,Engineer,https://jobs.example.test/123,2026-10-08\n'


def test_import_is_all_or_nothing(store, tmp_path):
    path = tmp_path / 'jobs.csv'
    path.write_text(HEADER + ROW + 'Bad,Other,http://bad.test/12,2026-10-08\n')
    with pytest.raises(ValueError):
        import_csv(store, path)
    assert not store.runs()


def test_import_skips_jobs_already_tracked(store, tmp_path):
    path = tmp_path / 'jobs.csv'
    path.write_text(HEADER + ROW + ROW.replace('/123', '/123?utm_source=mail'))
    assert import_csv(store, path) == (1, 1)
    assert import_csv(store, path) == (0, 2)
    run = store.runs()[0]
    assert run.pipeline == 'applied' and run.submitted_at == '2026-10-08'


@pytest.mark.parametrize('notes', ['=HYPERLINK("bad")', '\t=HYPERLINK("bad")', '+1', '-1', '@SUM(A1)'])
def test_export_neutralizes_spreadsheet_formulas(tmp_path, notes):
    path = tmp_path / 'jobs.csv'
    export_csv([ApplicationRun(job_url='https://jobs.example.test/1', notes=notes)], path)
    with open(path, newline='', encoding='utf-8') as stream:
        assert next(csv.DictReader(stream))['notes'] == "'" + notes


def test_activity_counts_confirmed_submissions_as_applied():
    runs = [ApplicationRun(job_url='https://jobs.example.test/1', pipeline='applied', submitted_at='2026-10-08T10:00:00'),
            ApplicationRun(job_url='https://jobs.example.test/2', pipeline='interviewing', submitted_at='2026-10-08'),
            ApplicationRun(job_url='https://jobs.example.test/3', submission_confirmed=True)]
    pipeline, daily, submitted, interviews = activity(runs)
    assert (pipeline['applied'], pipeline['interviewing'], pipeline['saved']) == (2, 1, 0)
    assert daily == {'2026-10-08': 2}
    assert (submitted, interviews) == (3, 1)
