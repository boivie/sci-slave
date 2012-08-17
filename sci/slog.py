"""
    sci.slog
    ~~~~~~~~

    SCI Streaming Log

    A build will stream structured log data to the job server.

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import json


class LogItem(object):
    def __init__(self):
        self.params = {}

    def serialize(self):
        d = dict(type = self.type)
        if self.params:
            d['params'] = self.params
        return json.dumps(d)


class StepBegun(LogItem):
    type = 'step-begun'

    def __init__(self, name, args, kwargs, log_start):
        self.params = dict(name = name, args = args, kwargs = kwargs,
                           log_start = log_start)


class StepJoinBegun(LogItem):
    type = 'step-join-begun'

    def __init__(self, name, time):
        self.params = dict(name = name, time = int(time))


class StepJoinDone(LogItem):
    type = 'step-join-done'

    def __init__(self, name, time):
        self.params = dict(name = name, time = int(time))


class StepDone(LogItem):
    type = 'step-done'

    def __init__(self, name, time, log_start, log_end):
        self.params = dict(name = name, time = int(time),
                           log_start = log_start, log_end = log_end)


class JobBegun(LogItem):
    type = 'job-begun'


class JobDone(LogItem):
    type = 'job-done'


class JobErrorThrown(LogItem):
    type = 'job-error'

    def __init__(self, what):
        self.params = dict(what = what)


class SetDescription(LogItem):
    type = 'set-description'

    def __init__(self, description):
        self.params = dict(description = description)


class SetBuildId(LogItem):
    type = 'set-build-id'

    def __init__(self, build_uuid):
        self.params = dict(build_id = build_uuid)


class AsyncJoined(LogItem):
    type = 'async-joined'

    def __init__(self, session_no, time):
        self.params = dict(session_no = int(session_no),
                           time = int(time))


class ArtifactAdded(LogItem):
    type = 'artifact-added'

    def __init__(self, filename, url, description = None):
        self.params = dict(filename = filename,
                           url = url)
        if description:
            self.params['description'] = description
