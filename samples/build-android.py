#!/usr/bin/env python
#
# Description:
#    Builds android (several products and variants) and saves the
#    resulting images as zip-files.
#
# Tags: [android, zipped]
#
# Parameters:
#  BRANCH:
#    description: Manifest branch
#    required: True
#
#  BUILD_ID_PREFIX:
#    description: The build ID prefix to use
#
#  PRODUCTS:
#    description: The products to build (will be guessed if not specified)
#    type: array
#
#  MANIFEST_URL:
#    description: Manifest URL
#    default: git://localhost/scitest/manifest.git
#
#  MANIFEST_FILE:
#    description: Manifest filename
#    default: default.xml
#
#  REPO_SYNC_JOBS:
#    description: The number of parallel connections when fetching source
#                 code using the repo tool.
#    default: 4
#
#  NUMBER_CPUS:
#    description: The number of CPUs on this machine
#    read-only: true
#    default: 4
#
#  VARIANTS:
#    description: Variants to build
#    type: checkbox
#    options: [eng, userdebug, user]
#    default: [eng, userdebug, user]
#
import time
from sci import Build

build = Build(__name__, debug = True)


@build.default("PRODUCTS")
def get_products():
    """A function that will be evaluated to get the default
       value for 'products' in case it's not specified"""

    if "donut" in build.env['BRANCH']:
        return ["g1", "emulator"]
    if "eclair" in build.env['BRANCH']:
        return ["droid", "nexus_one", "emulator"]
    if "gingerbread" in build.env['BRANCH']:
        return ["nexus_one", "nexus_s", "emulator"]
    build.error("Don't know which products to build!")


@build.default("BUILD_ID_PREFIX")
def default_build_id_prefix():
    return build.env['BRANCH'].upper().replace("-", "_")


@build.step("Create Build ID")
def create_build_id():
    build_id = build.env['BUILD_ID_PREFIX'] + "_" + time.strftime("%Y%m%d_%H%M%S")
    return build_id


@build.step("Create Static Manifest")
def create_manifest():
    """These commands will automatically run in a temporary directory
       that will be wiped once the entire job finishes"""
    build.run("repo init -u {{MANIFEST_URL}} -b {{BRANCH}} -m {{MANIFEST_FILE}}")
    build.run("repo sync --jobs={{REPO_SYNC_JOBS}}", name = "sync")
    build.run("repo manifest -r -o static_manifest.xml")

    # Upload the result of this step to the 'file storage node'
    build.artifacts.add("static_manifest.xml")


@build.step("Get source code")
def get_source():
    build.run("repo init -u {{MANIFEST_URL}} -b {{BRANCH}}")
    build.run("cp static_manifest.xml .repo/manifest.xml")
    build.run("repo sync --jobs={{REPO_SYNC_JOBS}}")


@build.step("Build Android")
def build_android():
    build.run("""
. build/envsetup.sh
lunch {{PRODUCT}}-{{VARIANT}}
make -j{{NUMBER_CPUS}}""")


@build.step("ZIP resulted files")
def zip_result():
    zip_file = "result-{{SCI_BUILD_ID}}-{{PRODUCT}}-{{VARIANT}}.zip"
    input_files = "out/target/product/{{PRODUCT}}/*.img"

    description = "Flashable images for {{PRODUCT}}-{{VARIANT}}"
    build.artifacts.create_zip(zip_file, input_files,
                               description = description)
    return build.format(zip_file)


@build.async()
@build.step("Run single asynchronous job")
def run_single_job(product, variant):
    """This job will be running on a separate machine, in parallel with
       a lot of other similar jobs. It will perform a few build steps."""
    build.env["PRODUCT"] = product
    build.env["VARIANT"] = variant
    build.artifacts.get("static_manifest.xml")

    get_source()
    build_android()
    return zip_result()


@build.step("Run matrix jobs")
def run_matrix_jobs():
    """Running jobs asynchronously"""
    results = []
    for product in build.env["PRODUCTS"]:
        for variant in build.env["VARIANTS"]:
            async_result = run_single_job(product, variant)
            results.append(async_result)

    for result in results:
        print("Result: " + result.get())


@build.step("Send Report")
def send_report():
    pass


@build.main()
def main():
    """This is the job's entry point."""
    # Note: setting build.build_id also defines SCI_BUILD_ID
    build.build_id = create_build_id()
    create_manifest()
    run_matrix_jobs()
    send_report()


if __name__ == "__main__":
    build.start()
