"""DOM evidence shared by the scanner, answer resolver and desktop engine."""
from dataclasses import dataclass, field as dataclass_field


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
