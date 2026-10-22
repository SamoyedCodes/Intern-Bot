"""Reconcile Workday's grouped, read-only review with the fields already verified."""
import re
from pathlib import Path

from core.automation.answers import resolve
from core.automation.fields import FormField
from core.automation.models import normalized


def workday_review_error(previous, summary, profile, run, answers):
    expected, actual = {}, {}
    for item in summary:
        key = (normalized(item['label']), item['group'], item['row'])
        if key in actual:
            return f'Duplicate review field: {item["label"]}.'
        actual[key] = normalized(item['value'])
    for assessment in previous:
        field = FormField(key=assessment.key, label=assessment.label, selector='', kind=assessment.kind,
                          group=assessment.group, row=assessment.row, required=assessment.required,
                          split_phone=normalized(assessment.label) == 'phone number' and any(normalized(a.label) == 'country phone code' for a in previous))
        answer = resolve(field, profile, run, answers)
        if answer.value is None and not answer.omit:
            return f'The approved answer for {field.label} is no longer available.'
        value = '' if answer.omit else Path(str(answer.value)).name if field.kind == 'file' else answer.value
        key = (normalized(field.label), field.group, field.row)
        if key in expected and expected[key] != value:
            return f'Conflicting preparation checkpoints: {field.label}.'
        expected[key] = value

    def combine(label, parts, required):
        key = (label, '', 0)
        if key not in actual:
            return
        if not all((part, '', 0) in expected for part in required):
            return
        expected[key] = ' '.join(str(expected.pop((part, '', 0))) for part in parts if (part, '', 0) in expected)

    combine('legal name', ['prefix', 'given name(s) - western script', 'middle name', 'family name - western script', 'suffix'],
            ['given name(s) - western script', 'family name - western script'])
    # shortcut: this observed English address layout; other country layouts must still match exactly or hand off.
    combine('address', ['street name', 'address line 2', 'city', 'postal code', 'country'], ['street name', 'country'])
    phone_keys = [(label, '', 0) for label in ['country phone code', 'phone number', 'phone device type']]
    if ('phone', '', 0) in actual and all(key in expected for key in phone_keys):
        code = re.search(r'\((\+\d+)\)$', str(expected[phone_keys[0]]))
        extension = expected.get(('phone extension', '', 0), '')
        if code and not extension:
            number = re.sub(r'\D', '', str(expected[phone_keys[1]]))
            expected[('phone', '', 0)] = f'{code[1]}{number}({expected[phone_keys[2]]})'
            actual[('phone', '', 0)] = re.sub(r'\s', '', actual[('phone', '', 0)])
            for key in phone_keys + [('phone extension', '', 0)]:
                expected.pop(key, None)

    for label, group, row in list(expected):
        if group in {'experience', 'education'} and label in {'from year', 'to year'}:
            prefix = label.split()[0]
            key, month = (prefix, group, row), (prefix + ' month', group, row)
            year = str(expected.pop((label, group, row)))
            expected[key] = f'{int(expected.pop(month)):02d}/{year}' if month in expected else year
        if not group and ' — ' in label and isinstance(expected.get((label, group, row)), bool):
            question = normalized(label.rsplit(' — ', 1)[0])
            key = (question, '', 0)
            if key not in actual:
                continue
            choices = [k for k in expected if k[1:] == ('', 0) and ' — ' in k[0] and normalized(k[0].rsplit(' — ', 1)[0]) == question]
            if all(isinstance(expected[k], bool) for k in choices):
                expected[key] = '; '.join(k[0].rsplit(' — ', 1)[1] for k in choices if expected[k])
                for choice in choices:
                    del expected[choice]
    for before, after in [('type to add skills', 'skills'), ('resume', 'resume/cv')]:
        key = (before, '', 0)
        if key in expected and (after, '', 0) in actual:
            expected[(after, '', 0)] = expected.pop(key)
    # The signed-in account email is read-only on My Information, so there was no input checkpoint for it.
    email = ('email address', '', 0)
    if email in actual and email not in expected:
        expected[email] = profile.email
    for key in expected.keys() | actual.keys():
        value = expected.get(key)
        accepted = ({'yes', 'true', 'checked'} if value else {'no', 'false', 'unchecked'}) if isinstance(value, bool) else {normalized(str(value))}
        if key not in expected or key not in actual or actual[key] not in accepted:
            return f'Cannot reconcile {key[0]} on the saved review.'
    return ''
