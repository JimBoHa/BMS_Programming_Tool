#!/bin/zsh
set -e
bms_project_dir=${0:A:h}
cd "$bms_project_dir"
if [[ ! -x .venv/bin/python ]]; then
  print 'Set up the Python environment first; see README.md.'
  exit 1
fi
print 'BMS Studio: http://127.0.0.1:8765'
print 'Keep this Terminal window open. Press Control-C to stop the app.'
.venv/bin/python -m bms_tool serve --open-browser
