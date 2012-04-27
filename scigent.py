#!/usr/bin/env python
import os, sys
from optparse import OptionParser

from sci.slave import Slave

DEFAULT_PORT = 6700

usage = "usage: %prog [options] jobserver-url | stop"
parser = OptionParser(usage=usage)
hostname = os.uname()[1]
parser.add_option("--port", dest="port", default=DEFAULT_PORT,
                  help="port to use")
parser.add_option("--path", dest="path", default=".",
                  help="path to use")
parser.add_option("--nick", dest="nick", default=hostname,
                  help="nickname")
(opts, args) = parser.parse_args()

if len(args) == 0:
    print >> sys.stderr, "Missing jobserver (or 'stop' to exit)"
    sys.exit(1)

if args[0] == 'stop':
    Slave(opts.nick, '', 0, '').stop()
else:
    Slave(opts.nick, args[0], int(opts.port), opts.path).start()
