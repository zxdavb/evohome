#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
"""RAMSES-II compatble Transport/Protocol processor."""

import asyncio
from datetime import datetime as dt
import logging
from queue import PriorityQueue, Empty
from typing import List, Optional, Tuple  # Any

from serial import serial_for_url  # SerialException,
from serial_asyncio import SerialTransport

from .const import __dev_mode__
from .message import Message
from .packet import GatewayProtocol, SERIAL_CONFIG  # Packet,

MAX_BUFFER_SIZE = 200
WRITER_TASK = "writer_task"

_LOGGER = logging.getLogger(__name__)
if False and __dev_mode__:
    _LOGGER.setLevel(logging.DEBUG)


class Ramses2Transport(asyncio.Transport):
    """Interface for a message transport.

    There may be several implementations, but typically, the user does not implement
    new transports; rather, the platform provides some useful transports that are
    implemented using the platform's best practices.

    The user never instantiates a transport directly; they call a utility function,
    passing it a protocol factory and other information necessary to create the
    transport and protocol.  (E.g. EventLoop.create_connection() or
    EventLoop.create_server().)

    The utility function will asynchronously create a transport and a protocol and
    hook them up by calling the protocol's connection_made() method, passing it the
    transport.
    """

    def __init__(self, gwy, protocol, extra=None):
        _LOGGER.debug("RamsesTransport.__init__()")

        self._gwy = gwy

        self._protocols = []
        self.set_protocol(protocol)

        self._dispatcher = None  # the HGI80 interface (is a protocol)

        self._extra = {} if extra is None else extra

        self._is_closing = None
        self._que = PriorityQueue()  # maxsize=MAX_SIZE)

    def _set_dispatcher(self, dispatcher):
        _LOGGER.debug("RamsesTransport._set_dispatcher(%s)", dispatcher)

        async def pkt_dispatcher():
            while True:
                try:
                    cmd = self._que.get_nowait()

                except Empty:
                    if not self._is_closing:
                        await asyncio.sleep(0.05)
                        continue

                except AttributeError:  # when self._que == None, from abort()
                    break

                else:
                    if self._dispatcher:
                        _LOGGER.debug("RamsesTransport.pkt_dispatcher(%s)", cmd)
                        await self._dispatcher(cmd)
                    self._que.task_done()

            _LOGGER.debug("RamsesTransport.pkt_dispatcher(): connection_lost(None)")
            [p.connection_lost(None) for p in self._protocols]

        self._dispatcher = dispatcher
        self._extra[WRITER_TASK] = asyncio.create_task(pkt_dispatcher())

    def _pkt_receiver(self, pkt):
        _LOGGER.debug("RamsesTransport._pkt_receiver(%s)", pkt)

        def proc_msg_callback(msg: Message) -> None:
            # TODO: this needs to be a queue
            dtm = dt.now()
            [
                v["func"](False, *v["args"], **v["kwargs"])
                for v in self._gwy._callbacks.values()
                if not v.get("daemon") and v.get("timeout", dt.max) <= dtm
            ]  # first, alert expired callbacks

            self._gwy._callbacks = {
                k: v
                for k, v in self._gwy._callbacks.items()
                if v.get("daemon") or v.get("timeout", dt.max) > dtm
            }  # then, discard expired callbacks

            if msg._pkt._header in self._gwy._callbacks:
                callback = self._gwy._callbacks[msg._pkt._header]
                callback["func"](msg, *callback["args"], **callback["kwargs"])
                if not callback.get("daemon"):
                    del self._gwy._callbacks[msg._pkt._header]

        msg = Message(self._gwy, pkt)  # trap/logs all invalid msgs appropriately
        if msg._pkt._header in self._gwy._callbacks:
            proc_msg_callback(msg)

        [p.data_received(msg) for p in self._protocols]

    def close(self):
        """Close the transport.

        Buffered data will be flushed asynchronously. No more data will be received.
        After all buffered data is flushed, the protocol's connection_lost() method will
        (eventually) be called with None as its argument.
        """
        _LOGGER.debug("RamsesTransport.close()")

        self._is_closing = True

    def abort(self):
        """Close the transport immediately.

        Buffered data will be lost. No more data will be received. The protocol's
        connection_lost() method will (eventually) be called with None as its argument.
        """
        _LOGGER.debug("RamsesTransport.abort(): clearing buffered data")

        self._is_closing = True
        self._que = None

    def is_closing(self) -> Optional[bool]:
        """Return True if the transport is closing or closed."""
        _LOGGER.debug("RamsesTransport.is_closing()")

        return self._is_closing

    def get_extra_info(self, name, default=None):
        """Get optional transport information."""
        _LOGGER.debug("RamsesTransport.get_extra_info()")

        return self._extra.get(name, default)

    def set_protocol(self, protocol):
        """Set a new protocol.

        Allow multiple protocols per transport.
        """
        _LOGGER.debug("RamsesTransport.set_protocol(%s)", protocol)

        if protocol not in self._protocols:
            if len(self._protocols) > 1:
                raise ValueError("Exceeded maximum number of subscribing protocols")

            self._protocols.append(protocol)
            protocol.connection_made(self)

    def get_protocol(self) -> Optional[List]:
        """Return the current protocol.

        There can be multiple protocols per transport.
        """
        _LOGGER.debug("RamsesTransport.get_protocol()")

        return self._protocols

    def is_reading(self) -> Optional[bool]:
        """Return True if the transport is receiving."""
        _LOGGER.debug("RamsesTransport.is_reading()")

        raise NotImplementedError

    def pause_reading(self):
        """Pause the receiving end.

        No data will be passed to the protocol's data_received() method until
        resume_reading() is called.
        """
        _LOGGER.debug("RamsesTransport.pause_reading()")

        raise NotImplementedError

    def resume_reading(self):
        """Resume the receiving end.

        Data received will once again be passed to the protocol's data_received()
        method.
        """
        _LOGGER.debug("RamsesTransport.resume_reading()")

        raise NotImplementedError

    def set_write_buffer_limits(self, high=None, low=None):
        """Set the high- and low-water limits for write flow control.

        These two values control when to call the protocol's pause_writing() and
        resume_writing() methods. If specified, the low-water limit must be less than
        or equal to the high-water limit. Neither value can be negative. The defaults
        are implementation-specific. If only the high-water limit is given, the
        low-water limit defaults to an implementation-specific value less than or equal
        to the high-water limit. Setting high to zero forces low to zero as well, and
        causes pause_writing() to be called whenever the buffer becomes non-empty.
        Setting low to zero causes resume_writing() to be called only once the buffer is
        empty. Use of zero for either limit is generally sub-optimal as it reduces
        opportunities for doing I/O and computation concurrently.
        """
        _LOGGER.debug("RamsesTransport.set_write_buffer_limits()")

        raise NotImplementedError

    def get_write_buffer_size(self):
        """Return the current size of the write buffer."""
        _LOGGER.debug("RamsesTransport.get_write_buffer_size()")

        raise NotImplementedError

    def write(self, cmd):
        """Write some data bytes to the transport.

        This does not block; it buffers the data and arranges for it to be sent out
        asynchronously.
        """
        _LOGGER.debug("RamsesTransport.write(%s)", cmd)

        if self._is_closing:
            raise RuntimeError("transport is closing or has closed")

        # if not self._dispatcher:
        #     raise RuntimeError("transport has no dispatcher")

        if self._dispatcher:
            self._que.put_nowait(cmd)

    def writelines(self, list_of_cmds):
        """Write a list (or any iterable) of data bytes to the transport.

        The default implementation concatenates the arguments and calls write() on the
        result.list_of_cmds
        """
        _LOGGER.debug("RamsesTransport.writelines(%s)", list_of_cmds)

        for cmd in list_of_cmds:
            self.write(cmd)

    def write_eof(self):
        """Close the write end after flushing buffered data.

        This is like typing ^D into a UNIX program reading from stdin. Data may still be
        received.
        """
        _LOGGER.debug("RamsesTransport.write_eof()")

        raise NotImplementedError

    def can_write_eof(self) -> bool:
        """Return True if this transport supports write_eof(), False if not."""
        _LOGGER.debug("RamsesTransport.can_write_eof()")

        return False


class Ramses2Protocol(asyncio.Protocol):
    """Interface for a message protocol.

    The user should implement this interface.  They can inherit from this class but
    don't need to.  The implementations here do nothing (they don't raise
    exceptions).

    When the user wants to requests a transport, they pass a protocol factory to a
    utility function (e.g., EventLoop.create_connection()).

    When the connection is made successfully, connection_made() is called with a
    suitable transport object.  Then data_received() will be called 0 or more times
    with data (bytes) received from the transport; finally, connection_lost() will
    be called exactly once with either an exception object or None as an argument.

    State machine of calls:

    start -> CM [-> DR*] [-> ER?] -> CL -> end

    * CM: connection_made()
    * DR: data_received()
    * ER: eof_received()
    * CL: connection_lost()
    """

    def __init__(self, msg_handler, gwy) -> None:
        _LOGGER.debug("RamsesProtocol.__init__()")

        self._callback = msg_handler
        self._gwy = gwy

        self._transport = None
        self._pause_writing = None

    def connection_made(self, transport: Ramses2Transport) -> None:
        """Called when a connection is made."""
        _LOGGER.debug("RamsesProtocol.connection_made(%s)", transport)

        self._transport = transport

    def data_received(self, msg):
        """Called when some data is received."""
        _LOGGER.debug("RamsesProtocol.data_received(%s)", msg)

        self._callback(msg)

    async def send_data(self, cmd) -> None:
        """Called when some data is to be sent (not a callaback)."""
        _LOGGER.debug("RamsesProtocol.send_data(%s)", cmd)

        while self._pause_writing:
            asyncio.sleep(0.05)

        self._transport.write(cmd)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when the connection is lost or closed."""
        _LOGGER.debug("RamsesProtocol.connection_lost()")

        if exc is not None:
            pass
        self._transport.loop.stop()

    def pause_writing(self) -> None:
        """Called when the transport's buffer goes over the high-water mark."""
        _LOGGER.debug("RamsesProtocol.pause_writing()")

        self._pause_writing = True

    def resume_writing(self) -> None:
        """Called when the transport's buffer drains below the low-water mark."""
        _LOGGER.debug("RamsesProtocol.resume_writing()")

        self._pause_writing = False


def create_msg_stack(gwy, msg_handler) -> Tuple:
    """Utility function to provides a transport to an internal protocol."""
    # The architecture is: msg -> pkt -> ser

    msg_protocol = Ramses2Protocol(msg_handler, gwy)  # used for gwy._msg_callbacks
    msg_transport = Ramses2Transport(gwy, msg_protocol)

    return (msg_protocol, msg_transport)


def create_pkt_stack(gwy, msg_transport, serial_port) -> Tuple:
    """Utility function to provides a transport to an internal protocol."""
    # The architecture is: msg -> pkt -> ser

    # msg_protocol = Ramses2Protocol(msg_handler, gwy)  # used for gwy._msg_callbacks
    # msg_transport = Ramses2Transport(gwy, msg_protocol)

    pkt_handler = msg_transport._pkt_receiver
    ser_instance = serial_for_url(serial_port, **SERIAL_CONFIG)

    pkt_protocol = GatewayProtocol(pkt_handler, gwy)  # used for gwy._qos_callbacks
    pkt_transport = SerialTransport(gwy._loop, pkt_protocol, ser_instance)

    msg_transport._set_dispatcher(pkt_protocol.send_data)

    # msg_protocol2 = Ramses2Protocol(pkt_handler2, gwy)  # used for gwy._msg_callbacks
    # msg_transport.add_protocol(gwy._loop, msg_protocol2)

    return (pkt_protocol, pkt_transport)


def create_ramses_client(gwy, protocol_factory, msg_handler):
    """Utility function to provide a transport to a client protocol."""

    msg_protocol = protocol_factory(msg_handler)
    gwy.msg_transport._set_dispatcher(msg_protocol.send_data)

    return msg_protocol, gwy.msg_transport