#!/usr/bin/env python
"""
    sci.slave
    ~~~~~~~

    Slave Entrypoint

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import web, json, os, threading, subprocess
from sci.daemon import Daemon
from sci.session import Session, time
from sci.http_client import HttpClient
from sci.utils import random_sha1
import ConfigParser
from Queue import Queue, Full, Empty

urls = (
    '/dispatch', 'StartJob',
)

EXPIRY_TTL = 60
DEFAULT_PORT = 6700

app = web.application(urls, globals())

requestq = Queue()
cv = threading.Condition()


def jsonify(**kwargs):
    web.header('Content-Type', 'application/json')
    return json.dumps(kwargs)


def abort(status, data):
    print("> %s" % data)
    raise web.webapi.HTTPError(status = status, data = data)


class StartJob:
    def POST(self):
        if not put_item(web.data()):
            abort(412, "Busy")
        return jsonify(status = "started")


class StatusThread(threading.Thread):
    def __init__(self, js_url, node_id, nick, port):
        threading.Thread.__init__(self)
        self.kill_received = False
        self.registered = False
        self.js = HttpClient(js_url)
        self.node_id = node_id
        self.nick = nick
        self.port = port

    def ttl_expired(self):
        if web.config.last_status + EXPIRY_TTL < int(time.time()):
            return True

    def send_ping(self):
        web.config.last_status = int(time.time())
        print("%s pinging" % self.node_id)

        try:
            self.js.call("/agent/ping/%s" % self.node_id,
                         method = "POST")
        except:
            # Any exceptions while we ping indicate that the jobserver
            # is down/unavailable - so re-register and hope it works better.
            print("Exception while pinging - re-registering")
            self.registered = False

    def send_register(self):
        print("Registering")
        web.config.last_status = int(time.time())
        try:
            self.js.call("/agent/register",
                         input = {"id": self.node_id,
                                  'nick': self.nick,
                                  "port": self.port,
                                  "labels": [os.uname()[0], os.uname()[4]]})
            print("%s registered - listening to %d" % (self.node_id, self.port))
            self.registered = True
        except:
            print("Failed to register. Will try again")
            self.registered = False

    def run(self):
        while not self.kill_received:
            self.send_register()
            time.sleep(5)
            while not self.kill_received and self.registered:
                if self.ttl_expired():
                    self.send_ping()
                time.sleep(1)


def get_item():
    with cv:
        while True:
            try:
                item = requestq.get_nowait()
                if item == None:
                    # Our 'busy' marker. Guess we are not as busy as we
                    # believe right now.
                    continue
                # Oh, it succeeded. Let's act 'busy'
                requestq.put(None)
                break
            except Empty:
                cv.wait()
    return item


def put_item(item):
    """Returns False if the ExcutionThread is working"""
    with cv:
        try:
            requestq.put_nowait(item)
            cv.notify()
            return True
        except Full:
            return False


def replace_item(item):
    # Assumes that the queue already has an item in it.
    with cv:
        requestq.get()
        requestq.put(item)
        cv.notify()


class ExecutionThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.kill_received = False

    def send_available(self, session_id = None, result = None, output = None,
                       log_file = None):
        web.config.last_status = int(time.time())
        print("%s checking in (available)" % web.config.node_id)

        client = HttpClient(web.config._job_server)
        client.call("/agent/available/%s" % web.config.node_id,
                    input = {'session_id': session_id,
                             'result': result,
                             'output': output,
                             'log_file': log_file})

    def send_busy(self, session_id):
        web.config.last_status = int(time.time())
        print("%s checking in (busy)" % web.config.node_id)

        client = HttpClient(web.config._job_server)
        client.call("/agent/busy/%s" % web.config.node_id,
                    input = {'session_id': session_id})

    def run(self):
        self.send_available()
        while not self.kill_received:
            item = get_item()

            session_id = json.loads(item)['session_id']

            # Fetch session information
            js = HttpClient(web.config._job_server)
            info = js.call('/agent/session/%s' % session_id)

            session = Session.create(session_id)
            run_job = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   '..',
                                   "run_job.py")
            args = [run_job, web.config._job_server, session_id]
            stdout = open(session.logfile, "w")
            session.state = "running"
            session.save()
            proc = subprocess.Popen(args, stdin = subprocess.PIPE,
                                    stdout = stdout, stderr = subprocess.STDOUT,
                                    cwd = web.config._path)
            proc.stdin.write(json.dumps(info))
            proc.stdin.close()
            self.send_busy(session_id)
            return_code = proc.wait()
            session = Session.load(session.id)
            result = 'success'
            if return_code != 0:
                # We never do that. It must have crashed - clear the session
                print("Job CRASHED")
                print("Session ID: %s" % session_id)
                print("Session Path: %s" % session.path)
                print("Session Logfile: %s" % session.logfile)
                print("Run-info: %s" % item)
                session.return_code = return_code
                session.state = "finished"
                session.save()
                result = 'error'
            else:
                print("Job terminated")

            url = "/f/%s/%s.log" % (info['build_uuid'], session_id)
            ss = HttpClient(info['ss_url'])
            ss_res = ss.call(url, method = 'PUT',
                             input = open(session.logfile, 'rb'))
            if ss_res['status'] != 'ok':
                print("FAILED TO SEND LOG FILE")
                ss_res['url'] = ''

            output = session.return_value
            self.send_available(session_id, result, output, ss_res['url'])


class Slave(Daemon):
    def __init__(self, nickname, jobserver, port = DEFAULT_PORT, path = '.'):
        self.nick = nickname
        self.jobserver = jobserver
        self.port = port
        self.path = os.path.realpath(path)
        pidfile = '/tmp/scigent_%s' % nickname
        super(Slave, self).__init__(pidfile,
                                    stdout='/dev/stdout',
                                    stderr='/dev/stderr')

    def get_config(self, path):
        c = ConfigParser.ConfigParser()
        c.read(os.path.join(path, "config.ini"))
        try:
            return {"node_id": c.get("sci", "node_id")}
        except ConfigParser.NoOptionError:
            return None
        except ConfigParser.NoSectionError:
            return None

    def save_config(self, path, node_id):
        c = ConfigParser.ConfigParser()
        c.add_section('sci')
        c.set("sci", "node_id", node_id)
        with open(os.path.join(path, "config.ini"), "wb") as configfile:
            c.write(configfile)

    def run(self):
        if not os.path.exists(self.path):
            os.makedirs(self.path)

        web.config._job_server = self.jobserver
        web.config._path = self.path
        web.config.port = self.port
        web.config.nick = self.nick

        Session.set_root_path(web.config._path)

        config = self.get_config(web.config._path)
        if not config:
            node_id = 'A' + random_sha1()
            self.save_config(web.config._path, web.config.node_id)
        else:
            node_id = config["node_id"]
        web.config.node_id = node_id

        status = StatusThread(self.jobserver, node_id, self.nick, self.port)
        execthread = ExecutionThread()
        status.start()
        execthread.start()
        web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", self.port))
        status.kill_received = True
        execthread.kill_received = True
        put_item(None)
