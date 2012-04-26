"""
    sci.utils
    ~~~~~~~~~

    SCI Utilities

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import random, hashlib


def random_bytes(size):
    return "".join(chr(random.randrange(0, 256)) for i in xrange(size))


def random_sha1():
    return hashlib.sha1(random_bytes(20)).hexdigest()
