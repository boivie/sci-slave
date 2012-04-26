#!/usr/bin/env python
"""
    sci.slave
    ~~~~~~~

    Slave Entrypoint

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
from optparse import OptionParser
import web, json, os, threading, subprocess
from sci.session import Session, time
from sci.http_client import HttpClient
from sci.utils import random_sha1
import ConfigParser
from Queue import Queue, Full, Empty

urls = (
    '/dispatch', 'StartJob',
)

EXPIRY_TTL = 60

web.config.debug = False
app = web.application(urls, globals())

requestq = Queue()
cv = threading.Condition()


def get_config(path):
    c = ConfigParser.ConfigParser()
    c.read(os.path.join(path, "config.ini"))
    try:
        return {"node_id": c.get("sci", "node_id")}
    except ConfigParser.NoOptionError:
        return None
    except ConfigParser.NoSectionError:
        return None


def save_config(path, node_id):
    c = ConfigParser.ConfigParser()
    c.add_section('sci')
    c.set("sci", "node_id", node_id)
    with open(os.path.join(path, "config.ini"), "wb") as configfile:
        c.write(configfile)


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


class GetLog:
    def GET(self, sid):
        web.header('Content-type', 'text/plain')
        web.header('Transfer-Encoding', 'chunked')
        session = Session.load(sid)
        if not session:
            abort(404, "session not found")
        with open(session.logfile, "rb") as f:
            while True:
                data = f.read(4096)
                if not data:
                    break
                yield data


def send_available(session_id = None, result = None, output = None,
                   log_file = None):
    web.config.last_status = int(time.time())
    print("%s checking in (available)" % web.config.node_id)

    client = HttpClient(web.config._job_server)
    client.call("/agent/available/%s" % web.config.node_id,
                input = {'session_id': session_id,
                         'result': result,
                         'output': output,
                         'log_file': log_file})


def send_busy(session_id):
    web.config.last_status = int(time.time())
    print("%s checking in (busy)" % web.config.node_id)

    client = HttpClient(web.config._job_server)
    client.call("/agent/busy/%s" % web.config.node_id,
                input = {'session_id': session_id})


def send_ping():
    web.config.last_status = int(time.time())
    print("%s pinging" % web.config.node_id)

    client = HttpClient(web.config._job_server)
    client.call("/agent/ping/%s" % web.config.node_id,
                method = "POST")


def ttl_expired():
    if web.config.last_status + EXPIRY_TTL < int(time.time()):
        return True


class StatusThread(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.kill_received = False

    def run(self):
        # Wait a few seconds before starting - there will be an initial
        # status sent from ExecutionThread.
        time.sleep(3)
        while not self.kill_received:
            if ttl_expired():
                send_ping()
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

    def run(self):
        send_available()
        while not self.kill_received:
            item = get_item()

            session_id = json.loads(item)['session_id']

            # Fetch session information
            js = HttpClient(web.config._job_server)
            info = js.call('/agent/session/%s' % session_id)

            session = Session.create(session_id)
            run_job = os.path.join(os.path.dirname(os.path.realpath(__file__)),
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
            send_busy(session_id)
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
            send_available(session_id, result, output, ss_res['url'])


if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("-c", "--config", dest = "config",
                      help = "configuration file to use")
    parser.add_option("-g", "--debug",
                      action = "store_true", dest = "debug", default = False,
                      help = "debug mode - will allow all requests")
    parser.add_option("-p", "--port", dest = "port", default = 6700,
                      help = "port to use")
    parser.add_option("--path", dest = "path", default = ".",
                      help = "path to use")

    (opts, args) = parser.parse_args()

    web.config._job_server = args[0]

    if opts.config:
        raise NotImplemented()

    if not os.path.exists(opts.path):
        os.makedirs(opts.path)
    web.config._path = os.path.realpath(opts.path)

    Session.set_root_path(web.config._path)

    config = get_config(web.config._path)
    if not config:
        web.config.node_id = 'A' + random_sha1()
        save_config(web.config._path, web.config.node_id)
    else:
        web.config.node_id = config["node_id"]

    web.config.port = int(opts.port)

    print("Registering")
    client = HttpClient(web.config._job_server)
    hostname = "%s-%d" % (os.uname()[1], web.config.port)
    ret = client.call("/agent/register",
                      input = {"id": web.config.node_id,
                               'nick': hostname,
                               "port": web.config.port,
                               "labels": ["macos"]})
    print("%s: Running from %s, listening to %d" % (web.config.node_id, web.config._path, web.config.port))

    status = StatusThread()
    execthread = ExecutionThread()
    status.start()
    execthread.start()
    web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", int(opts.port)))
    status.kill_received = True
    execthread.kill_received = True
    put_item(None)
