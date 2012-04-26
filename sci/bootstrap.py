"""
    sci.bootstrap
    ~~~~~~~~~~~~~

    SCI Bootstrap


    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import os, imp, socket
from datetime import datetime
from .session import Session
from .environment import Environment


class Bootstrap(object):
    @classmethod
    def _find_build(cls, module):
        from .build import Build
        # Find the 'build' variable
        for k in dir(module):
            var = getattr(module, k)
            if issubclass(var.__class__, Build):
                return var
        raise Exception("Couldn't locate the Build variable")

    @classmethod
    def _find_entrypoint(cls, build, name):
        if not name:
            return build._mainfn
        for step in build.steps:
            if step.fun.__name__ == name:
                return step
        raise Exception("Couldn't locate entry point")

    @classmethod
    def create_env(cls, parameters, build_uuid, build_name):
        env = Environment()

        for param in parameters:
            env[param] = parameters[param]

        env.define("SCI_BUILD_UUID", "The unique build identifier",
                   read_only = True, source = "initial environment",
                   value = build_uuid)
        env.define("SCI_BUILD_ID", "The user-defined build identifier",
                   source = "initial environment",
                   value = build_name)
        env.define("SCI_BUILD_NAME", "The unique build name",
                   read_only = True, source = "initial environment",
                   value = build_name)

        hostname = socket.gethostname()
        if hostname.endswith(".local"):
            hostname = hostname[:-len(".local")]
        env.define("SCI_HOSTNAME", "Host Name", read_only = True,
                   value = hostname, source = "initial environment")

        now = datetime.now()
        env.define("SCI_DATETIME", "The current date and time",
                   read_only = True, source = "initial environment",
                   value = now.strftime("%Y-%m-%d_%H-%M-%S"))

        return env

    @classmethod
    def run(cls, job_server, session_id, info):
        session = Session.load(session_id)

        recipe_fname = os.path.join(session.path, 'build.py')
        with open(recipe_fname, 'w') as f:
            f.write(info['recipe'])

        run_info = info['run_info']
        env = run_info.get('env')
        if env:
            env = Environment.deserialize(env)
        else:
            env = Bootstrap.create_env(info['parameters'], info['build_uuid'],
                                       info['build_name'])

        mod = imp.new_module('recipe')
        mod.__file__ = recipe_fname
        execfile(recipe_fname, mod.__dict__)

        build = Bootstrap._find_build(mod)
        build.jobserver = job_server
        entrypoint = Bootstrap._find_entrypoint(build, run_info.get('step_fun'))

        args = run_info.get('args', [])
        kwargs = run_info.get('kwargs', {})
        ss_url = info['ss_url']
        ret = build._start(env, session, entrypoint, args, kwargs, ss_url)

        # Update the session
        session = Session.load(session.id)
        session.return_value = ret
        session.return_code = 0  # We finished without exceptions.
        session.state = "finished"
        session.save()
        return ret
