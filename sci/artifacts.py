"""
    sci.artifacts
    ~~~~~~~~~~~~~

    Artifacts

    Artifacts are the results of a build. They will be saved
    whereas all other intermediate files will be deleted
    upon the completion of a build.

    :copyright: (c) 2011 by Victor Boivie
    :license: Apache License 2.0
"""
import os, shutil, zipfile, glob
from sci.slog import ArtifactAdded
from .http_client import HttpClient, HttpRequest


class ArtifactException(Exception):
    pass


class Artifact(object):
    def __init__(self, filename):
        self.filename = filename


class ArtifactsBase(object):
    def __init__(self, job):
        self.job = job

    def _add(self, local_filename, remote_filename, **kwargs):
        raise NotImplemented()

    def add(self, local_filename, remote_filename = None,
            description = "", **kwargs):
        description = self.job.format(description, **kwargs)
        local_filename = self.job.format(local_filename, **kwargs)
        if self.job.debug:
            print("Storing '%s' on the storage node" % local_filename)
        local_filename = os.path.join(self.job.session.workspace,
                                      local_filename)
        local_filename = os.path.realpath(local_filename)
        if not remote_filename:
            remote_filename = os.path.relpath(local_filename,
                                              self.job.session.workspace)
        url = self._add(local_filename, remote_filename, **kwargs)
        self.job.slog(ArtifactAdded(remote_filename, url, description))
        return Artifact(remote_filename)

    def get(self, remote_filename, local_filename = None, **kwargs):
        if local_filename is None:
            local_filename = os.path.join(self.job.session.workspace,
                                          remote_filename)
        try:
            os.makedirs(os.path.dirname(local_filename))
        except OSError:
            pass
        return self._get(remote_filename, local_filename)

    def _get(self, remote_filename, local_filename, **kwargs):
        raise NotImplemented()

    def create_zip(self, zip_filename, input_files, upload = True,
                   description = "", **kwargs):
        zip_filename = self.job.format(zip_filename, **kwargs)
        input_files = self.job.format(input_files, **kwargs)

        if self.job.debug:
            print("Zipping '%s' and storing as %s" % \
                      (input_files, zip_filename))
        zip_filename = os.path.join(self.job.session.workspace,
                                    zip_filename)
        input_files = os.path.join(self.job.session.workspace,
                                   input_files)

        zf = zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED)
        for fname in glob.iglob(input_files):
            zf.write(fname, os.path.relpath(fname, self.job.session.workspace))
        zf.close()
        if upload:
            return self.add(zip_filename, description = description)
        else:
            return Artifact(zip_filename)


class Artifacts(ArtifactsBase):
    def __init__(self, job, storage_server):
        ArtifactsBase.__init__(self, job)
        self.client = HttpClient(storage_server)
        self.url = storage_server

    def _add(self, local_filename, remote_filename, **kwargs):
        url = "/f/%s/%s" % (self.job.build_uuid, remote_filename)
        result = self.client.call(url, method = "PUT",
                                  input = open(local_filename, "rb"))
        if result["status"] != "ok":
            raise ArtifactException("Failed to store %s to server: %s" % \
                                        (local_filename, result["status"]))
        return result['url']

    def _get(self, remote_filename, local_filename, **kwargs):
        path = "/f/%s/%s" % (self.job.build_uuid, remote_filename)
        with HttpRequest(self.url, path) as src:
            with open(local_filename, "wb") as dest:
                shutil.copyfileobj(src, dest)
