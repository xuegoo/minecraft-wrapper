# -*- coding: utf-8 -*-

# Copyright (C) 2016, 2017 - BenBaptist and Wrapper.py developer(s).
# https://github.com/benbaptist/minecraft-wrapper
# This program is distributed under the terms of the GNU
# General Public License, version 3 or later.

import traceback
import threading
import time
import json
import random
import os
import logging
import socket
from pprint import pprint

from api.helpers import getargs
from core.storage import Storage

# noinspection PyBroadException
try:
    # noinspection PyCompatibility,PyUnresolvedReferences
    from urllib.parse import unquote as urllib_unquote
except:
    # noinspection PyCompatibility,PyUnresolvedReferences
    from urllib import unquote as urllib_unquote

try:
    import pkg_resources
    import requests
except ImportError:
    pkg_resources = False
    requests = False


# noinspection PyBroadException
class Web(object):
    def __init__(self, wrapper):
        self.wrapper = wrapper
        self.api = wrapper.api
        self.log = logging.getLogger('Web')
        self.config = wrapper.config
        self.serverpath = self.config["General"]["server-directory"]
        self.pass_handler = self.wrapper.cipher
        self.socket = False
        self.storage = Storage("web", pickle=False)
        self.data = self.storage.Data

        # TODO temporary security code until pass words are fixed.
        self.onlyusesafe_ips = self.config["Web"]["safe-ips-use"]
        self.safe_ips = self.config["Web"]["safe-ips"]

        if "keys" not in self.data:
            self.data["keys"] = []

        # Register events
        self.api.registerEvent("server.consoleMessage", self.on_server_console)
        self.api.registerEvent("player.message", self.on_player_message)
        self.api.registerEvent("player.join", self.on_player_join)
        self.api.registerEvent("player.leave", self.on_player_leave)
        self.api.registerEvent("irc.message", self.on_channel_message)

        self.consoleScrollback = []
        self.chatScrollback = []
        self.memoryGraph = []
        self.loginAttempts = 0
        self.lastAttempt = 0
        self.disableLogins = 0

        # t = threading.Thread(target=self.update_graph, args=())
        # t.daemon = True
        # t.start()

    # ================ Start  and Run code section ================
    # ordered by the time they are referenced in the code.

    # def update_graph(self):
    #     while not self.wrapper.halt.halt:
    #         while len(self.memoryGraph) > 200:
    #             del self.memoryGraph[0]
    #         if self.wrapper.javaserver.getmemoryusage():
    #             self.memoryGraph.append(
    #                 [time.time(), self.wrapper.javaserver.getmemoryusage()])
    #        time.sleep(1)

    def wrap(self):
        """ Wrapper starts excution here (via a thread). """
        while not self.wrapper.halt.halt:
            try:
                if self.bind():
                    # cProfile.run("self.listen()", "cProfile-debug")
                    self.listen()
                else:
                    self.log.error(
                        "Could not bind web to %s:%d - retrying in 5 seconds" % (
                            self.config["Web"]["web-bind"],
                            self.config["Web"]["web-port"]))
            except:
                for line in traceback.format_exc().split("\n"):
                    self.log.error(line)
            time.sleep(5)
        # closing also calls storage.save().
        self.storage.close()

    def bind(self):
        """ Started by self.wrap() to bind socket. """
        if self.socket is not False:
            self.socket.close()
        try:
            self.socket = socket.socket()
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.config["Web"]["web-bind"],
                              self.config["Web"]["web-port"]))
            self.socket.listen(5)
            return True
        except:
            return False

    def listen(self):
        """ Excuted by self.wrap() to listen for client(s). """
        self.log.info("Web Interface bound to %s:%d" % (
            self.config["Web"]["web-bind"], self.config["Web"]["web-port"]))
        while not self.wrapper.halt.halt:
            sock, addr = self.socket.accept()
            # TODO temporary security code until pass words are fixed.
            if self.onlyusesafe_ips:
                if addr[0] not in self.safe_ips:
                    sock.close()
                    print("sorry charlie (an unathorized IP attempted connection)")
                    continue
                # self.log.debug("(WEB) Connection %s started" % str(addr))
            client = Client(self.wrapper, sock, addr, self)

            # t = threading.Thread(target=cProfile.runctx, args=("client.wrap()", globals(), locals(), "cProfile-debug"))
            # t.daemon = True
            # t.start()
            t = threading.Thread(target=client.wrap, args=())
            t.daemon = True
            t.start()
        self.storage.save()

    # ========== EVENTS SECTION ==========================

    def on_server_console(self, payload):
        while len(self.consoleScrollback) > 1000:
            try:
                del self.consoleScrollback[0]
            except:
                break
        self.consoleScrollback.append((time.time(), payload["message"]))

    def on_player_message(self, payload):
        while len(self.chatScrollback) > 200:
            try:
                del self.chatScrollback[0]
            except:
                break
        self.chatScrollback.append((time.time(), {"type": "player",
                                                  "payload": {
                                                      "player": payload[
                                                          "player"].username,
                                                      "message": payload[
                                                          "message"]}}))

    def on_player_join(self, payload):
        while len(self.chatScrollback) > 200:
            try:
                del self.chatScrollback[0]
            except:
                break
        self.chatScrollback.append((time.time(), {"type": "playerJoin",
                                                  "payload": {
                                                      "player": payload[
                                                          "player"].username}}))

    def on_player_leave(self, payload):
        while len(self.chatScrollback) > 200:
            try:
                del self.chatScrollback[0]
            except:
                break
        self.chatScrollback.append((time.time(), {"type": "playerLeave",
                                                  "payload": {
                                                      "player": payload[
                                                          "player"].username}}))

    def on_channel_message(self, payload):
        while len(self.chatScrollback) > 200:
            try:
                del self.chatScrollback[0]
            except:
                break
        self.chatScrollback.append(
            (time.time(), {"type": "irc", "payload": payload}))

    # ========== Externally-called Methods section ==========================

    def check_login(self, password):
        """
        Returns True or False to indicate login success.
         - Called by client.run_action, action="login"
        """

        # TODO this ought to indicate somewhere other than the console why a login failed
        # TODO - maybe use None and False? - None for timeout and False for wrong password...

        # Threshold for logins
        if time.time() - self.disableLogins < 60:
            return False

        # check password validity
        if self.pass_handler.check_pw(password, self.config["Web"]["web-password"]):
            return True

        # unsuccessful password attempt
        self.loginAttempts += 1
        if self.loginAttempts > 10 and time.time() - self.lastAttempt < 60:
            self.disableLogins = time.time()
            self.log.warning("Disabled login attempts for one minute")
        self.lastAttempt = time.time()
        return False

    def make_key(self, remember_me):
        a = ""
        z = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890!@-_"
        for i in range(64):
            a += z[random.randrange(0, len(z))]
        # a += chr(random.randrange(97, 122))
        self.data["keys"].append([a, time.time(), remember_me])
        print("KEY", a)
        return a

    def validate_key(self, key):
        # TODO for now..
        return True
        pprint(self.data)
        for i in self.data["keys"]:
            expire_time = 2592000
            if len(i) > 2:
                if i[2]:
                    expire_time = 21600
            if i[0] == key and time.time() - i[1] < expire_time:  # Validate key and ensure it's under a week old
                self.loginAttempts = 0
                return True
        return False

    def remove_key(self, key):
        for i, v in enumerate(self.data["keys"]):
            if v[0] == key:
                del self.data["keys"][i]


# noinspection PyBroadException
class Client(object):
    """ Client socket handler- Web and Client function together as a server. """
    def __init__(self, wrapper, socket_conn, addr, web):
        self.wrapper = wrapper
        self.config = wrapper.config
        self.socket = socket_conn
        self.addr = addr
        self.web = web
        self.request = ""
        self.log = wrapper.log
        self.api = wrapper.api
        self.socket.setblocking(30)

        # to be able to run console commands as console xplayer():
        self.command_payload = {"args": ""}
        self.web_admin = self.wrapper.xplayer

    def wrap(self):
        try:
            self.handle()
        except:
            error_is = traceback.format_exc()
            self.log.error("Internal error while handling web mode request:")
            self.log.error(error_is)
            self.headers(status="300 Internal Server Error")
            self.write("<h1>300 Internal Server Error</h1>\r\n%s" % error_is)
            self.close()

    def handle(self):
        while not self.wrapper.halt.halt:

            # read data from socket
            try:
                data = self.socket.recv(1024)
                if len(data) < 1:
                    self.close()
                    return

                buff = data.split("\r\n")
            except:
                self.close()
                break

            if len(buff) < 1:
                self.log.debug("Connection closed abnormally")
                return False

            for line in buff:
                args = line.split(" ")

                if getargs(args, 0) == "GET":
                    self.log.debug(args)
                    self.get(getargs(args, 1))

                if getargs(args, 0) == "POST":
                    self.request = getargs(args, 1)
                    self.headers(status="400 Bad Request")
                    self.write("<h1>Invalid request. Sorry.</h1>")

                # self.log.debug(args)

    def get(self, request):
        # print("GET request: %s" % request)

        if request in ("/", "index"):
            filename = "/index.html"
        elif request == "/admin":
            filename = "/admin.html"
        elif request == ".":
            self.headers(status="400 Bad Request")
            self.write("<h1>BAD REQUEST</h1>")
            self.close()
            return False
        elif request[0:7] == "/action":
            try:
                raw_dump = json.dumps(self.handle_action(request))
                # self.log.debug("RAW DUMP: %s", raw_dump)
                self.write(raw_dump)
            except:
                self.headers(status="300 Internal Server Error")
                print(traceback.format_exc())
            self.close()
            return False
        else:
            filename = request

        request = filename
        filename = request.replace("..", "").replace("%2F", "/").replace("\\", "").replace("+", " ")

        try:
            data = self.read(filename)
            self.headers(content_type=self.get_content_type(filename))
            self.write(data)
        except:
            self.headers(status="404 Not Found")
            self.write("<h1>404 Not Found</h4>")
        self.close()

    def handle_action(self, request):
        # def args(i):
        #    try:
        #        return request.split("/")[1:][i]
        #    except:
        #        return ""

        # def get(i):
        #    for a in args(1).split("?")[1].split("&"):
        #        if a[0:a.find("=")]:
        #            return urllib_unquote(a[a.find("=") + 1:])
        #    return ""

        info = self.run_action(request)
        if not info:
            return {"status": "error", "payload": "unknown_key"}
        elif info == EOFError:
            return {"status": "error", "payload": "permission_denied"}
        else:
            return {"status": "good", "payload": info}

    def run_action(self, request):
        # pprint(request)
        # Entire requested action
        request_action = request.split("/")[2] or ""

        # split the action into two parts - action and args
        action_parts = request_action.split("?")

        # get the action - read_server_props, halt_wrapper, server_action, etc
        action = action_parts[0]

        # develop args into a dictionary for later
        action_arg_list = action_parts[1].split("&")
        argdict = {"key": ""}
        for argument in action_arg_list:
            argparts = argument.split("=")
            argname = argument.split("=")[0]
            if len(argparts) > 1:
                value = argparts[1]
                value = value.replace("%2F", "/").replace("+", " ")
            else:
                value = ""
            argdict[argname] = value
        if action == "stats":
            if not self.config["Web"]["public-stats"]:
                return EOFError
            players = []
            for i in self.wrapper.servervitals.players:
                players.append(
                    {"name": i,
                     "loggedIn": self.wrapper.servervitals.players[i].loggedIn,
                     "uuid": str(self.wrapper.servervitals.players[i].mojangUuid)
                     })
            return {"playerCount": len(self.wrapper.servervitals.players),
                    "players": players}

        if action == "login":
            password = argdict["password"]
            remember_me = argdict["remember-me"]
            if remember_me == "true":
                remember_me = True
            else:
                remember_me = False
            if self.web.check_login(password):
                key = self.web.make_key(remember_me)
                self.log.info("%s logged in to web mode (remember me: %s)" % (
                    self.addr[0], remember_me))
                return {"session-key": key}
            else:
                self.log.warning("%s failed to login" % self.addr[0])
            return EOFError
        if action == "is_admin":
            if self.web.validate_key(argdict["key"]):
                print("ADMIN PASSED")
                return {"status": "good"}
            return EOFError
        if action == "logout":
            if self.web.validate_key(argdict["key"]):
                self.web.remove_key(argdict["key"])
                self.log.info("[%s] Logged out." % self.addr[0])
                return "goodbye"
            return EOFError
        if action == "read_server_props":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            with open("%s/server.properties" % self.web.serverpath, 'r') as f:
                file_contents = f.read()
            return file_contents
        if action == "save_server_props":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            props = argdict["props"]
            if not props:
                return False
            if len(props) < 10:
                return False
            with open("%s/server.properties" % self.web.serverpath, 'r') as f:
                f.write(props)
            return "ok"
        if action == "listdir":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            if not self.config["Web"]["web-allow-file-management"]:
                return EOFError
            safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWYXZ0123456789_-/ "
            path_unfiltered = argdict["path"]
            path = ""
            for i in path_unfiltered:
                if i in safe:
                    path += i
            if path == "":
                path = "."
            files = []
            folders = []
            listdir = os.listdir(path)
            listdir.sort()
            for p in listdir:
                fullpath = path + "/" + p
                if p[-1] == "~":
                    continue
                if p[0] == ".":
                    continue
                if os.path.isdir(fullpath):
                    folders.append(
                        {"filename": p, "count": len(os.listdir(fullpath))})
                else:
                    files.append(
                        {"filename": p, "size": os.path.getsize(fullpath)})
            return {"files": files, "folders": folders}
        if action == "rename_file":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            if not self.config["Web"]["web-allow-file-management"]:
                return EOFError
            ren_file = argdict["path"]
            rename = argdict["rename"]
            if os.path.exists(ren_file):
                try:
                    os.rename(ren_file, rename)
                except:
                    print(traceback.format_exc())
                    return False
                return True
            return False
        if action == "delete_file":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            if not self.config["Web"]["web-allow-file-management"]:
                return EOFError
            del_file = argdict["path"]
            if os.path.exists(del_file):
                try:
                    if os.path.isdir(del_file):
                        os.removedirs(del_file)
                    else:
                        os.remove(del_file)
                except:
                    print(traceback.format_exc())
                    return False
                return True
            return False
        if action == "halt_wrapper":
            # if not self.web.validate_key(argdict["key"]):
            #    return EOFError
            self.wrapper.shutdown()
        if action == "get_player_skin":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            if not self.wrapper.proxymode:
                return {"error": "Proxy mode not enabled."}
            uuid = argdict["uuid"]
            if uuid in self.wrapper.proxy.skins:
                skin = self.wrapper.proxy.getSkinTexture(uuid)
                if skin:
                    return skin
                else:
                    return None
            else:
                return None
        if action == "admin_stats":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            if not self.wrapper.javaserver:
                return
            refresh_time = float(argdict["last_refresh"])
            players = []
            for i in self.wrapper.servervitals.players:
                player = self.wrapper.servervitals.players[i]
                players.append({
                    "name": i,
                    "loggedIn": player.loggedIn,
                    "uuid": str(player.mojangUuid),
                    "isOp": player.isOp()
                })
            plugins = []
            for plugid in self.wrapper.plugins:
                plugin = self.wrapper.plugins[plugid]
                if plugin["good"]:
                    if plugin["description"]:
                        description = plugin["description"]
                    else:
                        description = None
                    plugins.append({
                        "name": plugin["name"],
                        "version": plugin["version"],
                        "description": description,
                        "summary": plugin["summary"],
                        "author": plugin["author"],
                        "website": plugin["website"],
                        "id": plugid,
                        "good": True
                    })
                else:
                    plugins.append({
                        "name": plugin["name"],
                        "good": False
                    })
            console_scrollback = []
            for line in self.web.consoleScrollback:
                if line[0] > refresh_time:
                    console_scrollback.append(line[1])
            chat_scrollback = []
            for line in self.web.chatScrollback:
                if line[0] > refresh_time:
                    chat_scrollback.append(line[1])
            memory_graph = []
            for line in self.web.memoryGraph:
                if line[0] > refresh_time:
                    memory_graph.append(line[1])
            return {"playerCount": len(self.wrapper.servervitals.players),
                    "players": players,
                    "plugins": plugins,
                    "server_state": self.wrapper.servervitals.state,
                    "wrapper_build": self.wrapper.getbuildstring(),
                    "console": console_scrollback,
                    "chat": chat_scrollback,
                    "level_name": self.wrapper.servervitals.worldname,
                    "server_version": self.wrapper.servervitals.version,
                    "motd": self.wrapper.servervitals.motd,
                    "refresh_time": time.time(),
                    "server_name": self.config["Web"]["server-name"],
                    "server_memory": self.wrapper.javaserver.getmemoryusage(),
                    "server_memory_graph": memory_graph,
                    "world_size": self.wrapper.servervitals.worldsize}
        if action == "console":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            self.wrapper.javaserver.console(argdict["execute"])
            self.log.info("[%s] Executed: %s" % (self.addr[0], argdict["execute"]))
            return True
        if action == "chat":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            message = argdict["message"]
            self.web.chatScrollback.append((time.time(), {"type": "raw",
                                                          "payload": "[WEB ADMIN] " + message}))
            self.wrapper.javaserver.broadcast("&c[WEB ADMIN]&r " + message)
            return True
        if action == "kick_player":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            player = argdict["player"]
            reason = argdict["reason"]
            self.log.info("[%s] %s was kicked with reason: %s" % (self.addr[0], player, reason))
            self.wrapper.javaserver.console("kick %s %s" % (player, reason))
            return True
        if action == "ban_player":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            player = argdict["player"]
            reason = argdict["reason"]
            self.log.info("[%s] %s was banned with reason: %s" % (self.addr[0], player, reason))
            self.wrapper.javaserver.console("ban %s %s" % (player, reason))
            return True
        if action == "change_plugin":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            plugin = argdict["plugin"]
            state = argdict["state"]
            if state == "enable":
                if plugin in self.wrapper.storage["disabled_plugins"]:
                    self.wrapper.storage["disabled_plugins"].remove(plugin)
                    self.log.info("[%s] Set plugin enabled: '%s'" % (self.addr[0], plugin))
                    self.wrapper.commands.command_reload(self.web_admin,
                                                         self.command_payload)
            else:
                if plugin not in self.wrapper.storage["disabled_plugins"]:
                    self.wrapper.storage["disabled_plugins"].append(plugin)
                    self.log.info("[%s] Set plugin disabled: '%s'" % (self.addr[0], plugin))
                    self.wrapper.commands.command_reload(self.web_admin,
                                                         self.command_payload)
        if action == "reload_plugins":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            self.wrapper.commands.command_reload(self.web_admin,
                                                 self.command_payload)
            return True
        if action == "server_action":
            if not self.web.validate_key(argdict["key"]):
                return EOFError
            command = argdict["action"]
            if command == "stop":
                reason = argdict["reason"]
                self.wrapper.javaserver.stop_server_command(reason)
                self.log.info("[%s] Server stop with reason: %s" % (self.addr[0], reason))
                return "success"
            elif command == "restart":
                reason = argdict["reason"]
                self.wrapper.javaserver.restart(reason)
                self.log.info("[%s] Server restart with reason: %s" % (self.addr[0], reason))
                return "success"
            elif command == "start":
                self.wrapper.javaserver.start()
                self.log.info("[%s] Server started" % (self.addr[0]))
                return "success"
            elif command == "kill":
                self.wrapper.javaserver.kill("Server killed by Web module...")
                self.log.info("[%s] Server killed." % self.addr[0])
                return "success"
            return {"error": "invalid_server_action"}
        return False

    def read(self, filename):
        return pkg_resources.resource_stream(__name__,
                                             "html/%s" % filename).read()

    def write(self, message):
        self.socket.send(message)

    def close(self):
        try:
            self.socket.close()
        except:
            pass

    def headers(self, status="200 Good", content_type="text/html", location=""):
        self.write("HTTP/1.1 %s\r\n" % status)
        if len(location) < 1:
            self.write("Content-Type: %s\r\n" % content_type)

        if len(location) > 0:
            self.write("Location: %s\r\n" % location)

        self.write("\r\n")

    def get_content_type(self, filename):
        ext = filename.split(".")[-1]
        if ext == "js":
            return "application/javascript"
        if ext == "css":
            return "text/css"
        if ext in ("txt", "html"):
            return "text/html"
        if ext in ("ico",):
            return"image/x-icon"
        return "application/octet-stream"


if __name__ == "__main__":
    pass
    print("passed and excuted")
    # line = "GET SOME MORE DATA Hoss"
    # i = 1
    # x = " ".join(line.split(" ")[i:])
    # y = line.split(" ")[i]
    print('/action/read_server_props?key=undefined'.split("/"))
