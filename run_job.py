#!/usr/bin/env python
#
# Syntax: ./run_job <jobserver> <session_id>
#
# It should be run with the current working directory set properly
#
import sys, json
from sci.bootstrap import Bootstrap

data = json.loads(sys.stdin.read())
Bootstrap.run(sys.argv[1], sys.argv[2], data)
