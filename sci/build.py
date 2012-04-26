"""
    sci.build
    ~~~~~~~~~

    Simple Continuous Integration

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
from optparse import OptionParser
import re, os, time, sys, types, subprocess, logging, json
from .environment import Environment
from .artifacts import Artifacts
from .session import Session
from .bootstrap import Bootstrap
from .http_client import HttpClient
from .slog import (StepBegun, StepDone, StepJoinBegun, StepJoinDone,
                   JobBegun, JobDone, JobErrorThrown, SetDescription,
                   SetBuildId, AsyncJoined)


re_var = re.compile("{{(.*?)}}")


class BuildException(Exception):
    pass


class BuildFunction(object):
    def __init__(self, name, fun, **kwargs):
        self.name = name
        self.fun = fun
        self.is_main = False
        self._is_entrypoint = False

    def __call__(self, *args, **kwargs):
        return self.fun(*args, **kwargs)


class Step(BuildFunction):
    def __init__(self, job, name, fun, **kwargs):
        BuildFunction.__init__(self, name, fun, **kwargs)
        self.job = job
        self._is_async = False

    def __call__(self, *args, **kwargs):
        if self._is_async and not self._is_entrypoint:
            ajob = AsyncJob(self.job, self, args, kwargs)
            ajob.run()
            self.job._async_jobs.append(ajob)
            return ajob
        self.job.slog(StepBegun(self.name, args, kwargs))
        time_start = time.time()
        self.job._current_step = self
        self.job._print_banner("Step: '%s'" % self.name)
        ret = self.fun(*args, **kwargs)

        # Wait for any unfinished detached jobs
        if self.job.has_running_asyncs():
            diff = (time.time() - time_start) * 1000
            self.job.slog(StepJoinBegun(self.name, diff))
            self.job.join_asyncs()
            diff = (time.time() - time_start) * 1000
            self.job.slog(StepJoinDone(self.name, diff))

        diff = (time.time() - time_start) * 1000
        self.job.slog(StepDone(self.name, diff))
        return ret


class MainFn(BuildFunction):
    def __init__(self, name, fun, **kwargs):
        BuildFunction.__init__(self, name, fun, **kwargs)
        self.is_main = True

STATE_PREPARED, STATE_RUNNING, STATE_DONE = range(3)


class AsyncJob(object):
    def __init__(self, job, step, args, kwargs):
        self.job = job
        self.step = step
        self.args = args
        self.kwargs = kwargs
        self.state = STATE_PREPARED
        self.session_id = None
        self.result = None

    def run(self):
        data = {'build_id': self.job.build_uuid,
                'job_server': self.job.jobserver,
                'labels': [],
                'parent': self.job.session.id,
                'run_info': {'step_fun': self.step.fun.__name__,
                             'step_name': self.step.name,
                             'args': self.args,
                             'kwargs': self.kwargs,
                             'env': self.job.env.serialize()}}
        self.ts_start = time.time()
        js = HttpClient(self.job.jobserver)
        res = js.call('/agent/dispatch', input = data)
        self.session_id = res['session_id']
        self.state = STATE_RUNNING

    def get(self):
        if self.state == STATE_DONE:
            return self.output
        assert(self.state == STATE_RUNNING)
        js = HttpClient(self.job.jobserver)
        res = js.call('/agent/result/%s' % self.session_id)
        self.output = res['output']
        self.result = res['result']
        self.state = STATE_DONE
        session_no = self.session_id.split('-')[-1]
        diff = (time.time() - self.ts_start) * 1000
        self.job.slog(AsyncJoined(session_no, diff))
        return self.output


class Build(object):
    def __init__(self, import_name, debug = False):
        self._import_name = import_name
        # The session is known when running - not this early
        self._session = None
        self.steps = []
        self._mainfn = None
        self._description = ""
        self._build_id = ""
        self.build_uuid = None
        self.debug = debug
        self._job_key = os.environ.get("SCI_JOB_KEY")
        self._current_step = None

        self.env = Environment()
        self._default_fns = {}
        self.artifacts = None,
        self.jobserver = "http://localhost:6697"
        self._async_jobs = []

    def has_running_asyncs(self):
        njobs = len([a for a in self._async_jobs if a.state == STATE_RUNNING])
        return njobs > 0

    def join_asyncs(self):
        for ajob in self._async_jobs:
            ajob.get()

        # Return all the return values
        res = [a.output for a in self._async_jobs]

        self._async_jobs = []
        return res

    def set_description(self, description):
        self._description = self.format(description)
        self.slog(SetDescription(self._description))

    def get_description(self):
        return self._description

    description = property(get_description, set_description)

    def set_build_id(self, build_id):
        self._build_id = self.format(build_id)
        self.env['SCI_BUILD_ID'] = self._build_id
        self.slog(SetBuildId(self._build_id))

    def get_build_id(self):
        return self._build_id

    build_id = property(get_build_id, set_build_id)

    def set_session(self, session):
        if self._session:
            raise BuildException("The session can only be set once")
        self._session = session

    def get_session(self):
        return self._session

    session = property(get_session, set_session)

    ### Decorators ###

    def async(self, **kwargs):
        def decorator(f):
            f._is_async = True
            return f
        return decorator

    def default(self, name, **kwargs):
        def decorator(f):
            self._default_fns[name] = f
            return f
        return decorator

    def step(self, name, **kwargs):
        def decorator(f):
            s = Step(self, name, f, **kwargs)
            self.steps.append(s)
            return s
        return decorator

    def main(self, **kwargs):
        def decorator(f):
            fn = MainFn('main', f)
            self._mainfn = fn
            return fn
        return decorator

    def _timestr(self):
        delta = int(time.time() - self.start_time)
        if delta > 59:
            return "%dm%d" % (delta / 60, delta % 60)
        return "%d" % delta

    def _print_banner(self, text, dash = "-"):
        prefix = "[+%s]" % self._timestr()
        dash_left = (80 - len(text) - 4 - len(prefix)) / 2
        dash_right = 80 - len(text) - 4 - len(prefix) - dash_left
        print("%s%s[ %s ]%s" % (prefix, dash * dash_left,
                                 text, dash * dash_right))

    def _parse_arguments(self, params):
        # Parse parameters
        parser = OptionParser()
        (opts, args) = parser.parse_args()

        # Parse parameters specified as args:
        for arg in args:
            if "=" in arg:
                k, v = arg.split("=", 2)
                params[k] = v

    def _start(self, env, session, entrypoint, args, kwargs, ss_url):
        # Must set time first. It's used when printing
        self.start_time = time.time()
        self.session = session
        self.artifacts = Artifacts(self, ss_url)
        self.build_uuid = env['SCI_BUILD_UUID']
        self.env = env

        if entrypoint.is_main:
            for name in self._default_fns:
                if not name in env:
                    env[name] = self._default_fns[name]()
            self.slog(JobBegun())
        self._print_banner("Preparing Job", dash = "=")

        self.env.print_values()

        self._print_banner("Starting Job", dash = "=")
        entrypoint._is_entrypoint = True
        ret = entrypoint.fun(*args, **kwargs)
        self._print_banner("Job Finished", dash = "=")
        if entrypoint.is_main:
            self.slog(JobDone())
        return ret

    def slog(self, item):
        url = '/slog/%s' % self.session.id
        HttpClient(self.jobserver).call(url, input = item.serialize(), raw = True)

    def start(self, params = {}):
        """Start a build manually (for testing)

           This method is only used when running a build manually by
           invoking the build script from the command line."""
        logging.basicConfig(level=logging.DEBUG)
        client = HttpClient(self.jobserver)

        # The build will contain all information necessary to build it,
        # also including parameters. Gather all those
        self._parse_arguments(params)

        # Save the recipe at the job server
        contents = open(sys.modules[self._import_name].__file__, "rb").read()
        result = client.call("/recipe/private.json",
                             input = {"contents": contents})
        recipe_id = result['ref']

        # Update the job to use this recipe and lock it to a ref
        contents = {'recipe': 'private',
                    'recipe_ref': recipe_id}
        result = client.call("/job/private",
                             input = {"contents": contents})
        job_ref = result['ref']

        # Create a build
        build_info = client.call('/build/create/private.json',
                                 input = {'job_ref': job_ref,
                                          'parameters': params})
        session = Session.create(build_info['session_id'])

        # Normally, the agents indicate when a session is started
        # and finishes, but since we run the job ourselves, we must
        # manually do it.
        client.call('/build/started/%s' % build_info['uuid'],
                    method = 'POST')
        info = client.call('/agent/session/%s' % session.id)
        res = Bootstrap.run(self.jobserver, session.id, info)
        client.call('/build/done/%s' % build_info['uuid'],
                    input = {'result': 'success',
                             'output': res})
        return res

    def run(self, cmd, **kwargs):
        """Runs a command in a shell

           The command will be run with the current working directory
           set to be the session's workspace.

           If the command fails, this method will raise an error
        """
        sys.stdout.flush()
        cmd = self.format(cmd, **kwargs)
        devnull = open("/dev/null", "r")
        p = subprocess.Popen(cmd,
                             shell = True,
                             executable = '/bin/bash',
                             stdin = devnull, stdout = sys.stdout,
                             stderr = sys.stderr,
                             cwd = self.session.workspace)
        p.communicate()
        sys.stdout.flush()
        if p.returncode != 0:
            self.error("External command returned result code %d: %s" %
                       (p.returncode, cmd))

    def _format(self, tmpl, **kwargs):
        while True:
            m = re_var.search(tmpl)
            if not m:
                break
            name = m.groups()[0]
            value = self.var(name, **kwargs)
            if not value:
                self.error("Failed to replace template variable %s" % name)
            tmpl = tmpl.replace("{{%s}}" % name, str(value))
        return tmpl

    def format(self, tmpl, **kwargs):
        if isinstance(tmpl, basestring):
            return self._format(tmpl, **kwargs)
        elif isinstance(tmpl, types.ListType):
            return [self._format(t, **kwargs) for t in tmpl]
        else:
            raise TypeError("Invalid type for format")

    def var(self, _key, **kwargs):
        value = kwargs.get(_key)
        if not value:
            value = self.env.get(_key)
        return value

    def error(self, what):
        self.slog(JobErrorThrown(what))
        raise BuildException(what)
