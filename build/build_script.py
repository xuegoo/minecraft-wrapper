#!/usr/bin/env python
# -*- coding: utf-8 -*-

# build fully, but not commit also:
# usage: python ./build/build_script.py . dev

import os
import time
import json
import hashlib
import argparse
import subprocess

parser = argparse.ArgumentParser(
    description='Build script for Wrapper.py!',
    epilog='Created by Jason Bristol')

parser.add_argument('source', type=str, default='.', help='the top level source directory')
parser.add_argument('branch', type=str, choices=('dev', 'stable'), default='dev',
                    help='branch to commit changes to')
parser.add_argument('--commit', '-c', action='store_true', help='commit changes to specified branch')
parser.add_argument('--message', '-m', type=str, default='build revision', help='commit message') 
parser.add_argument('--verbose', '-v', action='store_true', help='verbose flag')

args = parser.parse_args()


def build_wrapper(buildargs):
    os.chdir(buildargs.source)

    with open("build/version.json", "r") as f:
        version = json.loads(f.read())
        if "__build__" not in version:
            version["__build__"] = version["build"] + 1
        else:
            version["__build__"] += 1
        version["__branch__"] = buildargs.branch
        version["release_time"] = time.time()

    filetext = ("# -*- coding: utf-8 -*-\n"
                "# Do not edit this file to bump versions; it is built automatically"
                "\n\n__version__ = %s\n__build__ = %d\n__branch__ = '%s'\n" %
                (version["__version__"], version["__build__"], version["__branch__"]))

    with open("build/buildinfo.py", "w") as f:
        f.write(filetext)

    with open("wrapper/core/buildinfo.py", "w") as f:
        f.write(filetext)

    with open("build/version.json", "w") as f:
        f.write(json.dumps(version))

    if os.path.exists("Wrapper.py"):
        os.remove("Wrapper.py")  # Time to start with a clean Wrapper.py!
    # subprocess.Popen("zip Wrapper.py -r . -x *~ -x *pyc", shell=True).wait()

    # from the master branch (this works properly)
    # Hooray for calling zip from os.system() instead of using proper modules! :D
    print(os.path.curdir)
    os.system("ls")
    os.chdir("wrapper")
    os.system("zip ../Wrapper.py -r . -x *~ /.git* *.pyc")
    os.chdir("..")
    with open("./build/Wrapper.py.md5", "w") as f:
        f.write(hashlib.md5(open("./Wrapper.py", "r").read()).hexdigest())

    # Mainly just for me (benbaptist), since most people will probably want to build locally without committing.
    if buildargs.commit:
        subprocess.Popen("git add --update :/", shell=True).wait()
        subprocess.Popen("git commit -m 'Build %s %d | %s'" % (buildargs.branch, version["__build__"],
                                                               buildargs.message),
                         shell=True).wait()
        subprocess.Popen("git push", shell=True).wait()
    print("Built version %d (%s build)" % (version["__build__"], buildargs.branch))

# Don't try-except here (just hides errors)
build_wrapper(args)
