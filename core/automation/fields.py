"""DOM evidence shared by the scanner, answer resolver and desktop engine."""
import json
from dataclasses import dataclass, field as dataclass_field
from urllib.parse import urlsplit


@dataclass
class FormField:
    key: str
    label: str
    selector: str
    kind: str
    value: str | bool = ""
    options: list[str] = dataclass_field(default_factory=list)
    option: str = ""
    group: str = ""
    row: int = 0
    required: bool = False
    disabled: bool = False
    invalid: bool = False
    readonly: bool = False
    file_digest: str = ""
    uploaded: bool = False
    split_phone: bool = False


def form_snapshot(url, fields):
    """The scanned form as the engine last saw it, for the event log: its shape and the site's own wording, never what was entered."""
    shape = ('key', 'label', 'kind', 'selector', 'group', 'row', 'required', 'disabled', 'invalid', 'readonly', 'uploaded')
    parts = urlsplit(url)
    return json.dumps({'page': parts.netloc + parts.path, 'fields': [
        # ponytail: the first 12 options; keep them all if a wrong match ever turns on a later one.
        {**{k: f[k] for k in shape if f.get(k)}, 'filled': f.get('value') not in ('', False, None), 'options': f.get('options', [])[:12]}
        for f in fields]}, ensure_ascii=False)
