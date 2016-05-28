# -*- coding: utf-8 -*-

# region Modules
# ------------------------------------------------

# std
import socket
import threading
import time
import json

# third party
# (none)

# local
import proxy.mcpacket as mcpacket
from proxy.packet import Packet
from api.entity import Entity

# Py3-2
try:  # Manually define an xrange builtin that works indentically on both (to take advantage of xrange's speed in 2)
    xxrange = xrange
except NameError:
    xxrange = range
# endregion

# region Constants
# ------------------------------------------------

_STRING = 0
_JSON = 1
_UBYTE = 2
_BYTE = 3
_INT = 4
_SHORT = 5
_USHORT = 6
_LONG = 7
_DOUBLE = 8
_FLOAT = 9
_BOOL = 10
_VARINT = 11
_BYTEARRAY = 12
_BYTEARRAY_SHORT = 13
_POSITION = 14
_SLOT = 15
_UUID = 16
_METADATA = 17
_REST = 90
_RAW = 90
# endregion


# noinspection PyBroadException,PyUnusedLocal
class ServerConnection:
    def __init__(self, client, wrapper, ip=None, port=None):
        """
        Server receives "CLIENT BOUND" packets from server.  These are what get parsed (CLIENT BOUND format).
        'client.packet.send' - sends a packet to the client (use CLIENT BOUND packet format)
        'self.packet.send' - sends a packet back to the server (use SERVER BOUND packet format)
        This part of proxy 'pretends' to be the client interacting with the server.


        Args:
            client: The client to connect to the server
            wrapper:
            ip:
            port:

        Returns:

        """
        self.client = client
        self.wrapper = wrapper
        self.proxy = wrapper.proxy
        self.log = wrapper.log
        self.ip = ip
        self.port = port

        self.abort = False
        self.isServer = True
        self.server_socket = socket.socket()

        self.state = ProxServState.HANDSHAKE
        self.packet = None
        self.lastPacketIDs = []

        self.version = self.wrapper.javaserver.protocolVersion
        self._refresh_server_version()
        self.username = self.client.username

        # we are going to centralize this to client.servereid
        # self.eid = None  # WHAT IS THIS - code seemed to use it in entity and player id code sections !?
        # self.playereid = None

        self.headlooks = 0

    def _refresh_server_version(self):
        # Get serverversion for mcpacket use
        try:
            self.version = self.wrapper.javaserver.protocolVersion
        except AttributeError:
            # Default to 1.8 if no server is running
            # This can be modified to any version
            self.version = 47

        # Determine packet types - currently 1.8 is the lowest version supported.
        if mcpacket.Server194.end() >= self.version >= mcpacket.Server194.start():  # 1.9.4
            self.pktSB = mcpacket.Server194
            self.pktCB = mcpacket.Client194
        elif mcpacket.Server19.end() >= self.version >= mcpacket.Server19.start():  # 1.9 - 1.9.3 Pre 3
            self.pktSB = mcpacket.Server19
            self.pktCB = mcpacket.Client19
        else:  # 1.8 default
            self.pktSB = mcpacket.Server18
            self.pktCB = mcpacket.Client18
        if self.version > mcpacket.PROTOCOL_1_7:
            # used by ban code to enable wrapper group help display for ban items.
            self.wrapper.api.registerPermission("mc1.7.6", value=True)

    def send(self, packetid, xpr, payload):  # not supported... no docstring. For backwards compatability purposes only.
        self.log.debug("deprecated server.send() called.  Use server.packet.sendpkt for best performance.")
        self.packet.send(packetid, xpr, payload)
        pass

    def connect(self):
        if self.ip is None:
            self.server_socket.connect(("localhost", self.wrapper.config["Proxy"]["server-port"]))
        else:
            self.server_socket.connect((self.ip, self.port))
            self.client.isLocal = False

        self.packet = Packet(self.server_socket, self)
        self.packet.version = self.client.clientversion

        t = threading.Thread(target=self.flush, args=())
        t.daemon = True
        t.start()

    def close(self, reason="Disconnected", kill_client=True):
        self.log.debug("Last packet IDs (Server -> Client) of player %s before disconnection: \n%s", self.username,
                       self.lastPacketIDs)
        self.abort = True
        self.packet = None
        try:
            self.server_socket.close()
        except OSError:
            pass

        if not self.client.isLocal and kill_client:  # Ben's cross-server hack
            self.client.isLocal = True
            self.client.packet.sendpkt(self.pktCB.CHANGE_GAME_STATE, [_UBYTE, _FLOAT], (1, 0))  # "end raining"
            self.client.packet.sendpkt(self.pktCB.CHAT_MESSAGE, [_STRING, _BYTE],
                                       ("{text:'Disconnected from server: %s', color:red}" %
                                       reason.replace("'", "\\'"), 0))
            self.client.connect()
            return

        # I may remove this later so the client can remain connected upon server disconnection
        #  - - -- - if re-activating code ;;;; update arguments!!   --- -- --
        # self.client.packet.send(0x02, "string|byte",
        #                         (json.dumps({"text": "Disconnected from server. Reason: %s" % reason,
        #                                       "color": "red"}),0))
        # self.abort = True
        # self.client.connect()
        if kill_client:
            self.client.abort = True
            self.client.server = None
            self.client.close()

    def getPlayerByEID(self, eid):
        for client in self.wrapper.proxy.clients:
            if client.servereid == eid:
                return self.getPlayerContext(client.username, calledby="getPlayerByEID")
        self.log.error("Failed to get any player by client Eid: %s", eid)
        return False

    def getPlayerContext(self, username, calledby=None):
        try:
            return self.wrapper.javaserver.players[username]
        except Exception as e:  # This could be masking an issue and would result in "False" player objects
            self.log.error("getPlayerContext (called by: %s) failed to get player %s: \n%s", calledby, username, e)
            return False

    def flush(self):
        while not self.abort:
            try:
                self.packet.flush()
            except socket.error:
                self.log.debug("serverconnection socket closed (bad file descriptor), closing flush..")
                self.abort = True
                break
            time.sleep(0.03)

    def parse(self, pkid):  # client - bound parse ("Server" class connection)

        if pkid == 0x00 and self.state < ProxServState.PLAY:  # disconnect, I suppose...
            message = self.packet.readpkt([_STRING])
            self.log.info("Disconnected from server: %s", message)
            self.client.disconnect(message)
            self.log.trace("(PROXY SERVER) -> Parsed 0x00 packet with server state < 3")
            return False

        if self.state == ProxServState.PLAY:
            # handle keep alive packets from server... nothing special here; we will just keep the server connected.
            if pkid == self.pktCB.KEEP_ALIVE:
                if self.version < mcpacket.PROTOCOL_1_8START:
                    data = self.packet.readpkt([_INT])
                    self.packet.sendpkt(self.pktSB.KEEP_ALIVE, [_INT], data)
                else:  # self.version >= mcpacket.PROTOCOL_1_8START: - future elif in case protocol changes again.
                    data = self.packet.readpkt([_VARINT])
                    self.log.trace("keelalivedata %s ", data)
                    self.packet.sendpkt(self.pktSB.KEEP_ALIVE, [_VARINT], data)
                self.log.trace("(PROXY SERVER) -> Parsed KEEP_ALIVE packet with server state 3 (PLAY)")
                return False

            elif pkid == self.pktCB.CHAT_MESSAGE:
                rawstring, position = self.packet.readpkt([_STRING, _BYTE])

                try:
                    data = json.loads(rawstring.decode('utf-8'))  # py3
                    self.log.trace("(PROXY SERVER) -> Parsed CHAT_MESSAGE packet with server state 3 (PLAY):\n%s", data)
                except Exception as e:
                    return

                payload = self.wrapper.events.callevent("player.chatbox", {"player": self.client.getPlayerObject(),
                                                                           "json": data})

                if payload is False:  # reject the packet .. no chat gets sent to the client
                    return False
                #
                # - this packet is headed to a client.  The plugin's modification could be just a simple "Hello There"
                #   or the more complex minecraft json dictionary - or just a dictionary written as text:
                # """{"text":"hello there"}"""
                #   the minecraft protocol is just json-formatted string, but python users find dealing with a
                # dictionary easier
                #   when creating complex items like the minecraft chat object.
                elif type(payload) == dict:  # if payload returns a "chat" protocol dictionary http://wiki.vg/Chat
                    chatmsg = json.dumps(payload)
                    # send fake packet with modded payload
                    self.client.packet.sendpkt(self.pktCB.CHAT_MESSAGE, [_STRING, _BYTE], (chatmsg, position))
                    return False  # reject the orginal packet (it will not reach the client)
                elif type(payload) == str:  # if payload (plugin dev) returns a string-only object...
                    self.log.warning("player.Chatbox return payload sent as string")
                    self.client.packet.sendpkt(self.pktCB.CHAT_MESSAGE, [_STRING, _BYTE], (payload, position))
                    return False
                else:  # no payload, nor was the packet rejected.. packet passes to the client (and his chat)
                    return True  # just gathering info with these parses.

            elif pkid == self.pktCB.JOIN_GAME:
                if self.version < mcpacket.PROTOCOL_1_9_1PRE:
                    data = self.packet.readpkt([_INT, _UBYTE, _BYTE, _UBYTE, _UBYTE, _STRING])
                    #    "int:eid|ubyte:gm|byte:dim|ubyte:diff|ubyte:max_players|string:level_type")
                else:
                    data = self.packet.readpkt([_INT, _UBYTE, _INT, _UBYTE, _UBYTE, _STRING])
                    #    "int:eid|ubyte:gm|int:dim|ubyte:diff|ubyte:max_players|string:level_type")
                self.log.trace("(PROXY SERVER) -> Parsed JOIN_GAME packet with server state 3 (PLAY):\n%s", data)
                self.client.gamemode = data[1]
                self.client.dimension = data[2]
                self.client.servereid = data[0]
                # self.client.eid = data[0]  # This is the EID of the player on this particular server -
                # not always the EID that the client is aware of.  $$ ST00 note: Why would the eid be different!!??

                # this is an attempt to clear the gm3 noclip issue on relogging.
                self.client.packet.sendpkt(self.pktCB.CHANGE_GAME_STATE, [_UBYTE, _FLOAT], (3, self.client.gamemode))
                return True

            elif pkid == self.pktCB.TIME_UPDATE:
                data = self.packet.readpkt([_LONG, _LONG])
                # "long:worldage|long:timeofday")
                self.wrapper.javaserver.timeofday = data[1]
                self.log.trace("(PROXY SERVER) -> Parsed TIME_UPDATE packet:\n%s", data)
                return True

            elif pkid == self.pktCB.SPAWN_POSITION:
                data = self.packet.readpkt([_POSITION])
                #  javaserver.spawnPoint doesn't exist.. this is player spawnpoint anyway... ?
                # self.wrapper.javaserver.spawnPoint = data[0]
                if self.client.position == (0, 0, 0):  # this is the actual point of a players "login: to the "server"
                    self.client.position = data[0]
                    self.wrapper.events.callevent("player.spawned", {"player": self.client.getPlayerObject()})
                self.log.trace("(PROXY SERVER) -> Parsed SPAWN_POSITION packet:\n%s", data[0])
                return True

            elif pkid == self.pktCB.RESPAWN:
                data = self.packet.readpkt([_INT, _UBYTE, _UBYTE, _STRING])
                # "int:dimension|ubyte:difficulty|ubyte:gamemode|level_type:string")
                self.client.gamemode = data[2]
                self.client.dimension = data[0]
                self.log.trace("(PROXY SERVER) -> Parsed RESPAWN packet:\n%s", data)
                return True

            # this packet is just a server-correct item... it usually does not get from client to our server in time
            # see note at same client (server-bound) packet in clientconnection.py
            # Wrapper will handle the response here, just like the keep alives
            elif pkid == self.pktCB.PLAYER_POSLOOK:
                if self.version < mcpacket.Client18.end():
                    data = self.packet.readpkt([_DOUBLE, _DOUBLE, _DOUBLE, _FLOAT, _FLOAT])
                    # "double:x|double:y|double:z|float:yaw|float:pitch")
                    x, y, z, yaw, pitch = data
                    self.packet.sendpkt(self.pktSB.PLAYER_POSLOOK, [_DOUBLE, _DOUBLE, _DOUBLE, _FLOAT, _FLOAT],
                                        (x, y, z, yaw, pitch))
                else:
                    data = self.packet.readpkt([_DOUBLE, _DOUBLE, _DOUBLE, _FLOAT, _FLOAT, _VARINT])
                    # "double:x|double:y|double:z|float:yaw|float:pitch|varint:con")
                    x, y, z, yaw, pitch, conf = data
                    self.packet.sendpkt(self.pktSB.PLAYER_POSLOOK, [_DOUBLE, _DOUBLE, _DOUBLE, _FLOAT, _FLOAT, _VARINT],
                                        (x, y, z, yaw, pitch, conf))
                self.client.position = (x, y, z)  # not a bad idea to fill player position
                self.log.trace("(PROXY SERVER) -> Parsed PLAYER_POSLOOK packet:\n%s", data)
                return True  # it will be sent to the client to keep it honest.

            elif pkid == self.pktCB.USE_BED:
                data = self.packet.readpkt([_VARINT, _POSITION])
                # "varint:eid|position:location")
                self.log.trace("(PROXY SERVER) -> Parsed USE_BED packet:\n%s", data)
                if data[0] == self.client.servereid:
                    self.client.bedposition = data[0]  # get the players beddy-bye location!
                    self.wrapper.events.callevent("player.usebed", {"player": self.getPlayerByEID(data[0])})
                    # There is no reason to be fabricating a new packet from a non-existent client.eid
                    # self.client.packet.sendpkt(self.pktCB.USE_BED, [_VARINT, _POSITION],
                    #                            (self.client.eid, data[1]))
                return True

            elif pkid == self.pktCB.SPAWN_PLAYER:
                # This packet  is used to spawn other players into a player client's world.
                # is this packet does not arrive, the other player(s) will nto be visible to the client
                dt = self.packet.readpkt([_VARINT, _UUID, _REST])
                # 1.8 "varint:eid|uuid:uuid|int:x|int:y|int:z|byte:yaw|byte:pitch|short:item|rest:metadt")
                # 1.9 "varint:eid|uuid:uuid|int:x|int:y|int:z|byte:yaw|byte:pitch|rest:metadt")
                # We dont need to read the whole thing.
                clientserverid = self.proxy.getclientbyofflineserveruuid(dt[1])
                if clientserverid.uuid:
                    self.client.packet.sendpkt(self.pktCB.SPAWN_PLAYER,
                                               [_VARINT, _UUID, _RAW], (dt[0], clientserverid.uuid, dt[2]))
                    return False
                self.log.trace("(PROXY SERVER) -> Converted SPAWN_PLAYER packet:\n%s", dt)
                return True

            elif pkid == self.pktCB.SPAWN_OBJECT:
                # We really do not want to start parsing this unless we have a way to eliminate entities
                # that get destroyed
                if not self.wrapper.javaserver.world:  # that is what this prevents...
                    self.log.trace("(PROXY SERVER) -> did not parse SPAWN_OBJECT packet.")
                    return True  # return now.. why parse something we are no going to use?
                entityuuid = None
                ost = 0
                if self.version < mcpacket.PROTOCOL_1_9START:
                    dt = self.packet.readpkt([_VARINT, _BYTE, _INT, _INT, _INT, _BYTE, _BYTE])
                    # "varint:eid|byte:type_|int:x|int:y|int:z|byte:pitch|byte:yaw")
                else:
                    dt = self.packet.readpkt([_VARINT, _UUID, _BYTE, _INT, _INT, _INT, _BYTE, _BYTE, _REST])
                    # "varint:eid|uuid:objectUUID|byte:type_|int:x|int:y|int:z|byte:pitch|byte:yaw|int:info|
                    # short:velocityX|short:velocityY|short:velocityZ")
                    entityuuid = dt[1]
                    ost = 1
                # according to https://wiki.python.org/moin/PythonSpeed :
                # "Multiple [...] slower than individual assignment. For example "x,y=a,b" is slower than "x=a; y=b"
                # eid = dt[0]
                # type_ = dt[1 + ost]
                # x = dt[2 + ost]
                # y = dt[3 + ost]
                # z = dt[4 + ost]
                # pitch = dt[5 + ost]
                # yaw = dt[6 + ost]
                # However; why do that at all?
                self.wrapper.javaserver.world.entities[dt[0]] = Entity(dt[0], entityuuid, dt[1 + ost],
                                                                       (dt[2 + ost], dt[3 + ost], dt[4 + ost]),
                                                                       (dt[5 + ost], dt[6 + ost]), True)
                self.log.trace("(PROXY SERVER) -> Parsed SPAWN_OBJECT packet:\n%s", dt)
                return True

            elif pkid == self.pktCB.SPAWN_MOB:
                # we are not going to do all the parsing work unless we are storing the entity data
                # Storing this entity data has other issues; like removing stale items or "dead" items.
                if not self.wrapper.javaserver.world:
                    self.log.trace("(PROXY SERVER) -> did not parse SPAWN_MOB packet.")
                    return True
                entityuuid = None
                ost = 0
                if self.version < mcpacket.PROTOCOL_1_9START:
                    dt = self.packet.readpkt([_VARINT, _UBYTE, _INT, _INT, _INT, _BYTE, _BYTE, _BYTE, _REST])

                    # "varint:eid|ubyte:type_|int:x|int:y|int:z|byte:pitch|byte:yaw|"
                    # "byte:head_pitch|...
                    # STOP PARSING HERE: short:velocityX|short:velocityY|short:velocityZ|rest:metadata")
                else:
                    dt = self.packet.readpkt([_VARINT, _UUID, _UBYTE, _INT, _INT, _INT, _BYTE, _BYTE, _BYTE, _REST])
                    # ("varint:eid|uuid:entityUUID|ubyte:type_|int:x|int:y|int:z|"
                    # "byte:pitch|byte:yaw|byte:head_pitch|
                    # STOP PARSING HERE: short:velocityX|short:velocityY|short:velocityZ|rest:metadata")
                    entityuuid = dt[1]
                    ost = 1  # offset

                # eid, type_, x, y, z, pitch, yaw, head_pitch = \
                #     dt["eid"], dt["type_"], dt["x"], dt["y"], dt["z"], dt["pitch"], dt["yaw"], \
                #     dt["head_pitch"]
                self.log.trace("(PROXY SERVER) -> Parsed SPAWN_MOB packet:\n%s", dt)

                self.wrapper.javaserver.world.entities[dt[0]] = Entity(dt[0], entityuuid, dt[1 + ost],
                                                                       (dt[2 + ost], dt[3 + ost], dt[4 + ost], ),
                                                                       (dt[5 + ost], dt[6 + ost], dt[7 + ost]),
                                                                       False)
                return True

            elif pkid == self.pktCB.ENTITY_RELATIVE_MOVE:
                if not self.wrapper.javaserver.world:  # hereout, no further explanation.. See prior packet.
                    self.log.trace("(PROXY SERVER) -> did not parse ENTITY_RELATIVE_MOVE packet.")
                    return True
                if self.version < mcpacket.PROTOCOL_1_8START:
                    # NOTE: These packets need to be filtered for cross-server stuff.
                    return True
                data = self.packet.readpkt([_VARINT, _BYTE, _BYTE, _BYTE])
                # ("varint:eid|byte:dx|byte:dy|byte:dz")
                self.log.trace("(PROXY SERVER) -> Parsed ENTITY_RELATIVE_MOVE packet:\n%s", data)

                # TODO just FYI, this is unfinshed code.. there is no 'world' instance in current code for javaserver
                if self.wrapper.javaserver.world.getEntityByEID(data[0]) is not None:
                    self.wrapper.javaserver.world.getEntityByEID(data[0]).moveRelative((data[1], data[2], data[3]))
                return True

            elif pkid == self.pktCB.ENTITY_TELEPORT:
                if not self.wrapper.javaserver.world:
                    self.log.trace("(PROXY SERVER) -> did not parse ENTITY_TELEPORT packet.")
                    return True
                if self.version < mcpacket.PROTOCOL_1_8START:
                    # NOTE: These packets need to be filtered for cross-server stuff.
                    return True
                data = self.packet.readpkt([_VARINT, _INT, _INT, _INT, _REST])
                # ("varint:eid|int:x|int:y|int:z|byte:yaw|byte:pitch")

                self.log.trace("(PROXY SERVER) -> Parsed ENTITY_TELEPORT packet:\n%s", data)
                if self.wrapper.javaserver.world.getEntityByEID(data[0]) is not None:
                    self.wrapper.javaserver.world.getEntityByEID(data[0]).teleport((data[1], data[2], data[3]))
                return True

            elif pkid == self.pktCB.ATTACH_ENTITY:
                data = []
                leash = True  # False to detach
                if self.version < mcpacket.PROTOCOL_1_8START:
                    # NOTE: These packets need to be filtered for cross-server stuff.
                    return True
                # this changed somewhere in the pre - 1.9 snapshots
                # indeed, the packet meaning may have changed too (1.8 is leashing, 1.9 is attaching to minecarts, etc)
                if mcpacket.PROTOCOL_1_8START <= self.version < mcpacket.PROTOCOL_1_9START:
                    data = self.packet.readpkt([_VARINT, _VARINT, _BOOL])
                    leash = data[2]
                if self.version >= mcpacket.PROTOCOL_1_9START:
                    data = self.packet.readpkt([_VARINT, _VARINT])
                    if data[1] == -1:
                        leash = False
                # ("varint:eid|varint:vid|bool:leash")
                entityeid = data[0]  # not sure.. these might be reversed for 1.9!!!!
                vehormobeid = data[1]
                player = self.getPlayerByEID(entityeid)
                self.log.trace("(PROXY SERVER) -> Parsed ATTACH_ENTITY packet:\n%s", data)

                if player is None:
                    return True

                if entityeid == self.client.servereid:
                    if not leash:
                        self.wrapper.events.callevent("player.unmount", {"player": player})
                        self.log.debug("player unmount called for %s", player.username)
                        self.client.riding = None
                    else:
                        self.wrapper.events.callevent("player.mount", {"player": player, "vehicle_id": vehormobeid,
                                                                       "leash": leash})
                        self.client.riding = vehormobeid
                        self.log.debug("player mount called for %s on eid %s", player.username, vehormobeid)
                        if not self.wrapper.javaserver.world:
                            return
                        self.client.riding = self.wrapper.javaserver.world.getEntityByEID(vehormobeid)
                        self.wrapper.javaserver.world.getEntityByEID(vehormobeid).rodeBy = self.client
                return True

            elif pkid == self.pktCB.MAP_CHUNK_BULK:  # (packet no longer exists in 1.9)
                # no idea why this is parsed.. we are not doing anything with the data...
                if mcpacket.PROTOCOL_1_9START > self.version > mcpacket.PROTOCOL_1_8START:
                    data = self.packet.readpkt([_BOOL, _VARINT])
                    chunks = data[1]
                    skylightbool = data[0]
                    # ("bool:skylight|varint:chunks")
                    for chunk in xxrange(chunks):
                        meta = self.packet.readpkt([_INT, _INT, _USHORT])
                        # ("int:x|int:z|ushort:primary")
                        primary = meta[2]
                        bitmask = bin(primary)[2:].zfill(16)
                        chunkcolumn = bytearray()
                        for bit in bitmask:
                            if bit == "1":
                                # packetanisc
                                chunkcolumn += bytearray(self.packet.read_data(16 * 16 * 16 * 2))
                                if self.client.dimension == 0:
                                    metalight = bytearray(self.packet.read_data(16 * 16 * 16))
                                if skylightbool:
                                    skylight = bytearray(self.packet.read_data(16 * 16 * 16))
                            else:
                                # Null Chunk
                                chunkcolumn += bytearray(16 * 16 * 16 * 2)
                    self.log.trace("(PROXY SERVER) -> Parsed MAP_CHUNK_BULK packet:\n%s", data)
                return True

            elif pkid == self.pktCB.CHANGE_GAME_STATE:
                data = self.packet.readpkt([_UBYTE, _FLOAT])
                # ("ubyte:reason|float:value")
                if data[0] == 3:
                    self.client.gamemode = data[1]
                self.log.trace("(PROXY SERVER) -> Parsed CHANGE_GAME_STATE packet:\n%s", data)
                return True

            elif pkid == self.pktCB.SET_SLOT:
                if self.version < mcpacket.PROTOCOL_1_8START:
                    # NOTE: These packets need to be filtered for cross-server stuff.
                    return True
                data = self.packet.readpkt([_BYTE, _SHORT, _SLOT])
                # ("byte:wid|short:slot|slot:data")
                if data[0] == 0:
                    self.client.inventory[data[1]] = data[2]
                self.log.trace("(PROXY SERVER) -> Parsed SET_SLOT packet:\n%s", data)
                return True

            # if pkid == 0x30: # Window Items
            # I kept this one because we may want to re-implement this
            #   data = self.packet.read("byte:wid|short:count")
            #   if data["wid"] == 0:
            #       for slot in range(1, data["count"]):
            #           data = self.packet.readpkt("slot:data")
            #           self.client.inventory[slot] = data["data"]
            #   self.log.trace("(PROXY SERVER) -> Parsed 0x30 packet:\n%s", data)
            #    return True

            elif pkid == self.pktCB.PLAYER_LIST_ITEM:
                if self.version > mcpacket.PROTOCOL_1_8START:
                    head = self.packet.readpkt([_VARINT, _VARINT])
                    # ("varint:action|varint:length")
                    lenhead = head[1]
                    action = head[0]
                    z = 0
                    while z < lenhead:
                        serveruuid = self.packet.readpkt([_UUID])[0]
                        playerclient = self.client.proxy.getclientbyofflineserveruuid(serveruuid)
                        if not playerclient:
                            z += 1
                            continue
                        try:
                            # This is an MCUUID object, how could this fail? All clients have a uuid attribute
                            uuid = playerclient.uuid
                        except Exception as e:
                            # uuid = playerclient
                            self.log.exception("playerclient.uuid failed in playerlist item (%s)", e)
                            z += 1
                            continue
                        z += 1
                        if action == 0:
                            properties = playerclient.properties
                            raw = ""
                            for prop in properties:
                                raw += self.client.packet.send_string(prop["name"])
                                raw += self.client.packet.send_string(prop["value"])
                                if "signature" in prop:
                                    raw += self.client.packet.send_bool(True)
                                    raw += self.client.packet.send_string(prop["signature"])
                                else:
                                    raw += self.client.packet.send_bool(False)
                            raw += self.client.packet.send_varInt(0)
                            raw += self.client.packet.send_varInt(0)
                            raw += self.client.packet.send_bool(False)
                            self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM,
                                                       [_VARINT, _VARINT, _UUID, _STRING, _VARINT, _RAW],
                                                       (0, 1, playerclient.uuid, playerclient.username,
                                                        len(properties), raw))
                        elif action == 1:
                            data = self.packet.readpkt([_VARINT])
                            gamemode = data[0]
                            # ("varint:gamemode")
                            self.log.trace("(PROXY SERVER) -> Parsed PLAYER_LIST_ITEM packet:\n%s", data)
                            self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM,
                                                       [_VARINT, _VARINT, _UUID, _VARINT],
                                                       (1, 1, uuid, gamemode))
                        elif action == 2:
                            data = self.packet.readpkt([_VARINT])
                            ping = data[0]
                            # ("varint:ping")
                            self.log.trace("(PROXY SERVER) -> Parsed PLAYER_LIST_ITEM packet:\n%s", data)
                            self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM, [_VARINT, _VARINT, _UUID, _VARINT],
                                                       (2, 1, uuid, ping))
                        elif action == 3:
                            data = self.packet.readpkt([_BOOL])
                            # ("bool:has_display")
                            hasdisplay = data[0]
                            if hasdisplay:
                                data = self.packet.readpkt([_STRING])
                                displayname = data[0]
                                # ("string:displayname")
                                self.log.trace("(PROXY SERVER) -> Parsed PLAYER_LIST_ITEM packet:\n%s", data)
                                self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM,
                                                           [_VARINT, _VARINT, _UUID, _BOOL, _STRING],
                                                           (3, 1, uuid, True, displayname))
                            else:
                                self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM,
                                                           [_VARINT, _VARINT, _UUID, _VARINT],
                                                           (3, 1, uuid, False))
                        elif action == 4:
                            self.client.packet.sendpkt(self.pktCB.PLAYER_LIST_ITEM,
                                                       [_VARINT, _VARINT, _UUID], (4, 1, uuid))
                        return False
                else:  # version < 1.7.9 needs no processing
                    return True

            elif pkid == self.pktCB.DISCONNECT:
                message = self.packet.readpkt([_JSON])["json"]
                # ("json:json")["json"]
                self.log.info("Disconnected from server: %s", message)
                if not self.client.isLocal:  # TODO - multi server code
                    self.close()
                else:
                    self.client.disconnect(message)
                self.log.trace("(PROXY SERVER) -> Parsed DISCONNECT packet")
                return False

            else:
                return True  # no packets parsed - passing to client

        if self.state == ProxServState.LOGIN:
            if pkid == 0x01:
                # This is throwing a malformed json exception when online mode is set to true, this should be a json
                # string
                self.client.disconnect("Server is online mode. Please turn it off in server.properties. Wrapper.py "
                                       "will handle authentication on its own, so do not worry about hackers.")
                self.log.trace("(PROXY SERVER) -> Parsed 0x01 packet with server state 2 (LOGIN)")
                return False

            if pkid == 0x02:  # Login Success - UUID & Username are sent in this packet
                self.state = ProxServState.PLAY
                self.log.trace("(PROXY SERVER) -> Parsed 0x02 packet with server state 2 (LOGIN)")
                return False

            if pkid == 0x03 and self.state == ProxServState.LOGIN:  # Set Compression
                data = self.packet.readpkt([_VARINT])
                # ("varint:threshold")
                if data[0] != -1:
                    self.packet.compression = True
                    self.packet.compressThreshold = data[0]
                else:
                    self.packet.compression = False
                    self.packet.compressThreshold = -1
                self.log.trace("(PROXY SERVER) -> Parsed 0x03 packet with server state 2 (LOGIN):\n%s", data)
                time.sleep(10)
                return  # False

    def handle(self):
        try:
            while not self.abort:
                if self.abort:
                    self.close()
                    break
                try:
                    pkid, original = self.packet.grabPacket()
                    self.lastPacketIDs.append((hex(pkid), len(original)))
                    if len(self.lastPacketIDs) > 10:
                        for i, v in enumerate(self.lastPacketIDs):
                            del self.lastPacketIDs[i]
                            break
                except EOFError as eof:
                    # This error is often erroneous, see https://github.com/suresttexas00/minecraft-wrapper/issues/30
                    self.log.debug("Packet EOF (%s)", eof)
                    self.abort = True
                    self.close()
                    break
                except socket.error:  # Bad file descriptor occurs anytime a socket is closed.
                    self.log.debug("Failed to grab packet [SERVER] socket closed; bad file descriptor")
                    self.abort = True
                    self.close()
                    break
                except Exception as e1:
                    # anything that gets here is a bona-fide error we need to become aware of
                    self.log.debug("Failed to grab packet [SERVER] (%s):", e1)
                    return
                if self.parse(pkid) and self.client:
                    self.client.packet.sendRaw(original)
        except Exception as e2:
            self.log.exception("Error in the [SERVER] -> [PROXY] handle (%s):", e2)
            self.close()


class ProxServState:
    """
    This class represents proxy Server states
    """
    HANDSHAKE = 0  # actually unused here because, as a fake "client", we are not listening for connections
    # So we don't have to listen for a handshake.  We simply send a handshake to the server
    # followed by a login start packet and go straight to LOGIN mode.  HANDSHAKE in this
    # context might mean a server that is not started?? (proposed idea).

    # MOTD = 1  # not used. client.py handles MOTD functions

    LOGIN = 2  # login state packets
    PLAY = 3  # packet play state

    def __init__(self):
        pass
