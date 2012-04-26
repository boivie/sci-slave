"""
    sci.environment
    ~~~~~~~~~~~~~~~

    Environment Handling

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import types


class Environment(dict):
    def __init__(self):
        self.config = {}

    def serialize(self):
        return {"c": self.config,
                "v": dict(self)}

    @classmethod
    def deserialize(self, c):
        env = Environment()
        for k in c["v"]:
            env[k] = c["v"][k]
        for k in c["c"]:
            env.config[k] = c["c"][k]
        return env

    def define(self, name, description = "", read_only = False, source = "", value = None, final = True):
        if final and name in self.config:
            raise Exception("This environment variable has already been defined")
        if value:
            self[name] = value
        self.config[name] = {"read_only": read_only,
                             "description": description,
                             "source": source}

    def __setitem__(self, key, value):
        config = self.config.get(key, {})
        if config.get("read_only"):
            raise Exception("This environment variable is read only")
        dict.__setitem__(self, key, value)

    def merge(self, env_or_dict):
        if not env_or_dict:
            return

        # Copy non-readonly variables
        for k in env_or_dict:
            if not self.config.get(k, {}).get("read_only"):
                self[k] = env_or_dict[k]

        # Also copy configuration if possible
        if type(env_or_dict) is type(Environment):
            if k in env_or_dict.config:
                self.config[k] = env_or_dict.config[k]

    def print_values(self):
        def strfy(v):
            if (type(v)) in types.StringTypes:
                return "'%s'" % v
            return str(v)

        print("Environment:")
        for key in sorted(self):
            print(" %s: %s" % (key, strfy(self[key])))
