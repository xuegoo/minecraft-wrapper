#!/usr/bin/env python
# -*- coding: utf-8 -*-

# build fully, but not commit also:
# usage: python ./build/build_script.py . dev rc -i -d

from os import path, walk, chdir, remove, system
from glob import glob
import time
import json
import hashlib
import argparse

parser = argparse.ArgumentParser(
    description='Build script for Wrapper.py!',
    epilog='Created by Jason Bristol')

parser.add_argument('source', type=str, default='.',
                    help='the top level source directory')
parser.add_argument('branch', type=str, choices=('dev', 'stable'),
                    default='dev', help='branch name to build')
parser.add_argument('release', type=str, choices=(
                        'alpha', 'beta', 'rc', 'final'
                    ),
                    default='alpha', help='type of release (alpha, beta, etc)')
parser.add_argument('--incrementbuild', '-i', action='store_true',
                    help='increment the build number (for final builds)')
parser.add_argument('--docbuild', '-d', action='store_true',
                    help='Re-build Wrapper.py documentation')
parser.add_argument('--verbose', '-v', action='store_true',
                    help='verbose flag')

args = parser.parse_args()


def build_wrapper(buildargs):
    chdir(buildargs.source)

    if buildargs.docbuild:
        # build the events
        build_the_events()
        # build the docs
        build_the_docs()

    with open("build/version.json", "r") as f:
        version = json.loads(f.read())

    if len(version["__version__"]) < 4:
        version["__version__"].append(buildargs.release)
        version["__version__"].append(version["__build__"])

    version["__version__"][3] = buildargs.release

    if buildargs.incrementbuild:
        version["__version__"][4] += 1

    version["__branch__"] = buildargs.branch
    version["release_time"] = time.time()

    filetext = ("# -*- coding: utf-8 -*-\n"
                "# Do not edit this file to bump versions; "
                "it is built automatically\n\n"
                "__version__ = %s\n"
                "__branch__ = '%s'\n" %
                (version["__version__"],
                 version["__branch__"]))

    with open("build/buildinfo.py", "w") as f:
        f.write(filetext)
    with open("wrapper/core/buildinfo.py", "w") as f:
        f.write(filetext)

    with open("build/version.json", "w") as f:
        f.write(json.dumps(version, indent=4, sort_keys=True))

    if path.exists("Wrapper.py"):
        # Time to start with a clean Wrapper.py!
        remove("Wrapper.py")

    # Hooray for calling zip from system() instead of using proper
    # modules! :D
    system("ls")
    chdir("wrapper")
    system("zip ../Wrapper.py -r . -x *~ /.git* *.pyc *__pycache__* *test.py")
    chdir("..")
    system("zip Wrapper.py LICENSE.txt")

    wrapper_hash = hashlib.md5(open("./Wrapper.py", "rb").read()).hexdigest()
    with open("./build/Wrapper.py.md5", "w") as f:
        f.write(wrapper_hash)
    with open("./docs/Wrapper.py.md5", "w") as f:
        f.write(wrapper_hash)

    # removed committing code.  Want it back?  look at this commit:
    #  `https://github.com/benbaptist/minecraft-wrapper/commit/141e07e04f7d7f7c334c9b4bbfd92d537ff0188e`  # noqa


# Main documentation builder
def build_the_docs():
    """Simple docs builder.  creates 'ReStructured Text' files from the
    docstrings. Rst format based on spec:

    http://docutils.sourceforge.net/docs/ref/rst/restructuredtext.html
    """

    sep = '"""'
    copy_right = "<sup>Copyright (C) 2016 - 2018 - BenBaptist and Wrapper.py" \
                " developer(s).</sup>\n\n"
    index_file = "**Welcome to the Wrapper.py Plugin API documentation!" \
                 "**\n\nThe API is divided into modules.  Click on each " \
                 "module to see it's documentation.\n\n"

    events_footer = "<br>**Click here for a list of Wrapper's events**<br>" \
                    "[Wrapper.py Events](/documentation/events.rst)<br>"

    api_files = ["api/wrapperconfig", "api/base", "api/minecraft",
                 "api/player", "api/world", "api/entity", "api/backups",
                 "api/helpers"]
    processed = {}

    all_functions = "\n\n\n**Looking for a specific method?  search this list" \
                    " to see which api module has it:**\n\n"
    function_list = []

    for files in api_files:
        with open("wrapper/%s.py" % files) as f:
            data = f.read()
        all_items = data.split(sep)
        complete_doc = ""
        item_count = len(all_items) - 1
        total_items = range(0, item_count, 2)

        for each_item in total_items:
            # each_item.split(endsep)[0]
            item = all_items[each_item + 1]

            item_lines = item.splitlines()
            newlines = ""
            for alllines in item_lines:
                if alllines[-7:] != "# NODOC":
                    newlines += "%s\n" % alllines
            # remove trailing \n created at last entry
            item = newlines[:-1]

            # add classes and Defs
            header = "****\n"
            if "class " in all_items[each_item]:
                header = "**< class%s >**\n" % all_items[each_item].split(
                    "class")[1].split(":")[0]

            if "def " in all_items[each_item]:
                defs = all_items[each_item].split("def")
                # function_list.append("%s - %s" % (defs, files))
                number_of_defs = len(defs) - 1
                header = "- %s\n" % all_items[each_item].split(
                    "def")[number_of_defs].split(":")[0]

            # dont create documentation for private functions
            if "-  _" not in header and header != "****\n":
                print(header, item)
                if header[0:3] == "-  ":
                    function_list.append("%s -> [↩%s](#%s)" % (header.split("(")[0], files.split("/")[1], files.replace("/", "")))
                complete_doc = "%s\n%s%s\n" % (complete_doc, header, item)
        processed[files] = complete_doc

    function_list = sorted(function_list)
    all_functions += "\n".join(function_list)

    for files in api_files:
        with open("documentation/%s.rst" % files.split("/")[1], "w") as f:
            f.write(processed[files])
        index_file = "%s ##### [%s](/documentation/%s.rst)\n\n" % (
            index_file, files, files.split("/")[1])
    index_file += events_footer + "\n" + all_functions

    with open("documentation/readme.md", "w") as f:
        f.write(copy_right)
        f.write(index_file)


# process a file possibly containing events
def process_file(filetext, filename, data):
    # preserve intentional single space in quotes from stripping
    strippedtext = filetext.replace("\" \"", "<__SPACE__>")
    # strip all embedded whitespace
    strippedtext = ''.join(strippedtext.split())
    strippedtext = strippedtext.replace("<__SPACE__>", "\" \"")

    eventsections = strippedtext.split(".callevent")
    print("building %s events list" % filename)
    for eachsection in eventsections:
        if eachsection[0] != "(":
            # it is not a function (probably the part before the 1st one)
            continue
        time.sleep(.1)
        # all events have a name
        eventname = eachsection.split("(")[1].split(",")[0]

        rest = "".join(eachsection.split("%s," % eventname)[1:])
        arguments = get_the_args(rest)
        raw_event = filetext.split("%s," % eventname)
        myeventonly = raw_event[1].split(".callevent")

        event_doc = myeventonly[0].split("\"\"\"")

        if len(event_doc) > 2 and "eventdoc" in event_doc[1].lower():
            doc_area = event_doc[1]
        else:
            doc_area = None

        # initialize groups
        if "groups" not in data:
            data["groups"] = {}

        # basic doc
        doc_item = {
            "file": filename.split("/")[-1:][0] or filename,
            "group": "/".join(filename.split("/")[-2:]) or filename,
            "module": "/".join(filename.split("/")[-2:]) or filename,
            "event": eventname.strip("\""),
            "payload": "\n".join(arguments.lstrip("{").rstrip("}").replace(
                "\":", "\": ").split(",")) or None,
            "abortable": "",
            "comments": "",
            "description": ""
        }

        # enhanced doc (has a docstring with <marker> some data <marker>)
        if doc_area:
            if "internalfunction" in doc_area:
                # some items need to be scrubbed because they are just
                # internal workings of wrapper and not real events
                continue
            for items in doc_item:
                area = "<%s>" % items
                target = doc_area.split(area)
                # should be greater than 2 to ensure closing <marker> exists
                if len(target) > 2:
                    alllines = []
                    itemslines = target[1].splitlines()
                    for eachline in itemslines:
                        alllines.append(eachline.rstrip().lstrip())
                    # support <br> and <t> for line break and tabs
                    # ... and spaces (<sp>) -sometimes needed for rst
                    doc_item[items] = "\n".join(alllines).strip(
                        ).replace("<br>", "\n").replace(
                        "<t>", "    ").replace("<sp>", " ")

        # ensure group list exists
        if doc_item["group"] not in data["groups"]:
            data["groups"][doc_item["group"]] = []

        # append this item
        if doc_item not in data["groups"][doc_item["group"]] and doc_item["payload"] != "payload":  # noqa
            data["groups"][doc_item["group"]].append(doc_item)


# get the payload arguments for an event
def get_the_args(stringsection):

    toparse = "(%s" % stringsection
    counter = 0
    index = 0
    for counter, character in enumerate(toparse):
        if character == "(":
            index += 1
        if character == ")":
            index -= 1
        if index == 0:
            break
    return toparse[1:counter]


def format_to_rst(data):
    """take events dictionary data and return a text Rst file"""
    textfile = """# -*- coding: utf-8 -*-

***Wrapper Events***

    Each Wrapper event, once registered, will call back the passed function
    when the event occurs.  The call back function must reference the correct
    return payload.
    
    When a plugin calls an event which can be aborted, it is important that
    your code not delay in completing.  The proxy packet processing is on
    hold while your code decides what to do with the event.  If you take too 
    long, the client could be disconnected!  This is an aggregate time of
    all the plugins that call this event.
    
    :sample Plugin snippet:
    
        .. code:: python

            class Main:
                def __init__(self, api, log):
                    self.api = api
                    
            def onEnable(self):
                self.api.registerEvent("player.login", _player_login_callback)
            
            def _player_login_callback(self, payload):
                playername = payload["playername"]
                player_object = self.api.getPlayer(playername)
                self.api.minecraft.broadcast("%s joined the server!" % playername)
                player_object.message("Welcome to the server, %s" % playername)
                
        ..


"""  # noqa

    indent = "    "

    for group in data["groups"]:
        if len(data["groups"][group]) > 0:
            textfile += "**< Group '%s' >**\n\n" % group
        for group_item in data["groups"][group]:

            # Event name
            textfile += ":Event: \"%s\"\n\n" % group_item["event"]

            # module code name
            textfile += "%s:Module: %s *(%s)*\n\n" % (
                indent, group_item["file"], group_item["module"])

            # description - indented just like payload args
            # use <br> (line break) and <t> (tab/4space) for
            # additional formatting inside comment
            if group_item["description"] != "":
                textfile += "%s:Description:\n" % indent
                for lines in group_item["description"].splitlines():
                    textfile += "%s%s%s\n" % (indent, indent, lines)
                textfile += "\n"
            else:
                textfile += "%s:Description: %s\n\n" % (
                    indent, group_item["event"])

            # No payload lines
            if group_item["payload"] != "None":
                textfile += "%s:Payload:\n" % indent
                for lines in group_item["payload"].splitlines():
                    # if a start line (begins with quoted item)
                    if lines[0] == "\"":
                        textfile += "%s%s:%s\n" % (indent, indent, lines)
                    # likely a continuation line
                    else:
                        textfile += "%s%s %s\n" % (indent, indent, lines)
                textfile += "\n"
            else:
                textfile += "%s:Payload: None\n\n" % indent

            # abortable
            textfile += "%s:Can be aborted/modified: %s\n\n" % (
                indent, group_item["abortable"])

            # Comments - are indented just like payload args
            # use <br> (line break), <t> (tab/4space), <sp>
            # (one space) for additional formatting inside comment
            if group_item["comments"] != "":
                textfile += "%s:Comments:\n" % indent
                for lines in group_item["comments"].splitlines():
                    textfile += "%s%s%s\n" % (indent, indent, lines)
                textfile += "\n"
            else:
                textfile += "\n"
    return textfile


def build_the_events():
    """Build a Rst table(s) describing wrapper events"""

    # make list of all source code modules
    codefiles = [
        y for x in walk("wrapper") for y in glob(path.join(x[0], '*.py'))]

    # so that they are always in the same order..
    codefiles.sort()

    all_events = {}

    # get all items
    for filenames in codefiles:
        with open(filenames) as f:
            filecontent = f.read()
        # process_file changes the contexts of all_events without
        # an explicit return
        process_file(filecontent, filenames, all_events)

    # write the finished file
    with open("documentation/events.rst", "w") as f:
        f.write(format_to_rst(all_events))


if __name__ == "__main__":
    build_wrapper(args)
