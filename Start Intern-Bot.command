#!/bin/zsh
# Double-click in Finder to launch Intern-Bot. First run sets up .venv.
set -e
cd "${0:A:h}"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m playwright install chromium
fi

exec .venv/bin/python main.py
