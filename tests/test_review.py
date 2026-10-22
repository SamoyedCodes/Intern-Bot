"""Workday's modern review combines several editable fields into read-only values."""
import pytest

from core.automation.models import ApplicantProfile, ApplicationRun, ApprovedAnswer, Experience, FieldAssessment
from core.automation.review import workday_review_error
from tests.support import prepare, open_fixture


@pytest.mark.parametrize('change', ['', 'name', 'phone', 'date', 'omission', 'extra', 'duplicate'])
def test_grouped_workday_review_requires_all_exact_prepared_values(change):
    profile = ApplicantProfile(name_prefix='Mr', first_name='Ada', last_name='Example', email='ada@example.test', country='Singapore',
        address_line1='12 Example St', city='Singapore', postal_code='123456', phone_country_code='+65', phone_number='98765432', phone_device_type='Mobile',
        experience=[Experience(start_date='2026-05')])
    run = ApplicationRun(job_url='https://example.wd1.myworkdayjobs.com/job/example', profile_snapshot=profile)
    labels = ['Prefix', 'Given Name(s) - Western Script', 'Family Name - Western Script', 'Street Name', 'City', 'Postal Code', 'Country',
              'Country Phone Code', 'Phone Number', 'Phone Device Type', 'Phone Extension', 'From Month', 'From Year', 'Optional answer', 'Question* — Yes', 'Question* — No']
    previous = [FieldAssessment(key=label, label=label, section='preparation', disposition='intentionally_omitted' if label in {'Optional answer','Phone Extension'} else 'verified',
        group='experience' if label.startswith('From') else '', kind='checkbox' if ' — ' in label else 'text') for label in labels]
    answers = [ApprovedAnswer(question=q, value=v, omit=omit, scope='global') for q,v,omit in [
        ('Optional answer','',True), ('Phone Extension','',True), ('Question* — Yes',True,False), ('Question* — No',False,False)]]
    values = [('Legal Name','Mr Ada Example'), ('Address','12 Example St\nSingapore 123456\nSingapore'),
              ('Phone','+65 9876 5432 (Mobile)'), ('From','05/2026'), ('Optional answer',''), ('Question*','Yes'), ('Email Address','ada@example.test')]
    summary = [dict(label=label, value=value, group='experience' if label=='From' else '', row=0, layout='workday') for label,value in values]
    index = {'name':0,'phone':2,'date':3,'omission':4}
    if change in index:
        summary[index[change]]['value'] = 'Unexpected value'
    if change == 'extra':
        summary.append(dict(label='Unapproved answer',value='Yes',group='',row=0,layout='workday'))
    if change == 'duplicate':
        summary.append(summary[0].copy())
    assert bool(workday_review_error(previous, summary, profile, run, answers)) == bool(change)


async def test_modern_workday_review_reads_labels_and_repeated_rows_without_reusing_duplicate_ids(context, store):
    html = '''<div data-automation-id="applyFlowReviewPage">
    <div aria-labelledby="Legal-Name-section"><h4>Legal Name</h4><div><span id=name>Ada Example</span></div></div>
    <div role=group aria-labelledby="Work-Experience-section">
      <div role=group aria-labelledby="Work-Experience-1-panel"><div><label for=jobTitle>Job Title</label><div><span id=jobTitle>Engineer</span></div></div></div>
      <div role=group aria-labelledby="Work-Experience-2-panel"><div><label for=jobTitle>Job Title</label><div><span id=jobTitle>Tutor</span></div></div></div>
    </div>
    <div><div id=rich-label1><div data-automation-id=richText>Optional answer</div></div><div><span>No Response</span></div></div>
    <div><div id=rich-label2><div data-automation-id=richText>Question*</div></div><div><span><ul><li>Yes</li><li>Maybe</li></ul></span></div></div>
    <div aria-labelledby="skills-section"><h4>Skills</h4><ul data-automation-id=skills><li>Python</li></ul></div>
    <div aria-labelledby="Resume/CV-section"><h4>Resume/CV</h4><div data-automation-id=file-upload-item-name>resume.pdf</div></div>
    </div>'''
    page = await open_fixture(context, 'workday', html)
    bridge, _, _, _, _ = await prepare(page, store, 'workday')
    summary = (await bridge.command('snapshot'))['summary']
    assert [(s['label'], s['value'], s['group'], s['row']) for s in summary] == [
        ('Job Title','Engineer','experience',0), ('Job Title','Tutor','experience',1),
        ('Optional answer','','',0), ('Question*','Yes; Maybe','',0), ('Legal Name','Ada Example','',0),
        ('Skills','Python','',0), ('Resume/CV','resume.pdf','',0)]
    assert all(s['layout'] == 'workday' for s in summary)
