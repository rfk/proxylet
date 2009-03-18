"""

  proxylet:  lightweight HTTP reverse proxy built on eventlet

This module implements a lightweight reverse proxy for HTTP, using non-blocking
IO based on the eventlet module.  It aims to do as little as possible while
supporting simple request/response rewriting and being compatible with HTTP
keep-alive.

Basic operation is via the 'serve' function, which will bind to the
specified host and port and start accepting incoming HTTP requests:

  proxylet.serve(host,port,mapper)

Here 'mapper' is a function taking a proxylet.streams.HTTPRequest object,
and returning either None (for '404 Not Found') or a 3-tuple giving the
destination host, destination port, and a rewriter object.

The rewriter can be any callable that takes request and response streams
as arguments and returns wrapped versions of them, but it will most likely
be a subclass of proxylet.relocate.Relocator.  This class has the necessary
logic to rewrite the request for proxying.

As an example of the available functionality, this mapping function will
proxy requests to /svn to a private subversion server, requests to /files
to a private fileserver, and return 404 for any other paths:

  def mapper(req):
    svn = SVNRelocator("http://www.example.com/svn","http://svn.example.com/")
    if svn.matchesLocal(req.reqURI):
      return svn.mapping  # contains the (host,port,rewriter) tuple
    if req.reqURI.startswith("/files/"):
      return ("files.example.com",80,None)
    return None

"""

__ver_major__ = 0
__ver_minor__ = 1
__ver_patch__ = 1
__ver_sub__ = ""
__version__ = "%d.%d.%d%s" % (__ver_major__,__ver_minor__,
                              __ver_patch__,__ver_sub__)


import sys
import traceback
import socket
from eventlet import api as evtapi
from streams import *


def uspawn(func):
    """Decorator spawning a microthread for each call to a function."""
    def uspawner(*args,**kwds):
        evtapi.spawn(func,*args,**kwds)
    uspawner.__name__ = func.__name__
    uspawner.__doc__ = func.__doc__
    return uspawner


class Dispatcher:
    """Class that dipatches requests from a client socket.

    HTTP requests are read from the client socket, and passed to the
    mapper function.  This determines what host/port combination to proxy
    the request to, as well as any rewriting to be performed.

    Different requests from the same socket may be proxied to different
    servers.  All sockets are kept open until one is closed, at which point
    all other sockets are closed as well.  This allows the proxy to be
    compatible with HTTP keep-alive without implementing any details.
    """

    def __init__(self,client,mapper):
        self.client = CallOnClose(client,self.onclose)
        self.mapper = mapper
        self.servers = {}
        self._closed = False
        # To ensure responses are read and delivered in order, we
        # process them sequentially out of a queue.
        self._responses = []
        self._processingResps = False

    @uspawn
    def dispatch(self):
        """Request dispatch loop."""
        try:
         while not self._closed:
          try:
            req = HTTPRequest(self.client)
          except (IOError,socket.error):
            break
          # If an invalid request is received, send 400 Bad Request
          # and close the connection immediately
          if not req.valid:
            resp = StringStream("HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
            self.onclose()
            self.sendResponse(resp)
            break
          mapping = self.mapper(req)
          if mapping is None:
            content = "Not Found"
            resp = StringStream("HTTP/1.1 404 Not Found\r\nContent-Length: %d\r\n\r\n%s" % (len(content),content))
            server = Nullify([])
          else:
            (host,port,rewriter) = mapping
            port = int(port)
            server = self._getServer(host,port)
            resp = HTTPResponse(server)
            if rewriter is not None:
              (req,resp) = rewriter(req,resp)
          self.sendResponse(resp)
          self.sendRequest(req,server)
        except:
          (_,ex,tb) = sys.exc_info()
          traceback.print_tb(tb)
          print ex
        # Ensure all responses have been written, before closing
        self.processResponses()

    def _getServer(self,host,port):
        destn = (host,port)
        try:
          return self.servers[destn]
        except KeyError:
          server = evtapi.connect_tcp(destn)
          server = CallOnClose(server,self.onclose)
          self.servers[destn] = server
          return server

    def onclose(self):
        self._closed = True

    def doclose(self):
        self.client.close()
        for s in self.servers:
          self.servers[s].close()

    def sendResponse(self,resp):
        """Queue a response object for processing."""
        self._responses.append(resp)
        # The processing loop may have terminated, make sure it starts again
        self.processResponses()

    def sendRequest(self,req,server):
        for ln in req:
          server.write(ln)
        
    @uspawn
    def processResponses(self):
        if self._processingResps:
          return
        self._processingResps = True
        while self._responses:
          resp = self._responses.pop(0)        
          for ln in resp:
            try:
              self.client.write(ln)
            except (IOError,socket.error):
              break
          if self._closed:
            self.doclose()
        self._processingResps = False


class Server:
    """Stand-alone reverse proxy server class.

    Create like so:

        Server(host,port,mapper)

    Here host and port specify where to bind the server, and mapper is a
    function that takes a HTTPRequest object, and returns a 3-tuple giving
    the destination host, destination port, and a rewriting function (or
    None, if no rewriting is required).

    To run the server, call its "serve" method.  It can be halted by
    calling the "halt" method.
    """

    def __init__(self,host,port,mapper):
        self.host = host
        self.port = int(port)
        self.mapper = mapper

    def halt(self):
        self._running = False

    def serve(self):
        self._running = True
        socket = evtapi.tcp_listener((self.host,self.port))
        while self._running:
          client, _ = socket.accept()
          Dispatcher(client,self.mapper).dispatch()
        socket.close()


def serve(host,port,mapper):
    """Convenience function to immediately start a server instance."""
    s = Server(host,port,mapper)
    s.serve()


def _demo_mapper(req):
    """Simple demonstration mapper function, also for testing purposes.
    Proxies the following:
        * /rfk/      :   my personal website
        * /g/        :   google website
        * /morph/    :   morph SVN repo
    """
    from relocate import DrupalRelocator, DAVRelocator, SVNRelocator, Relocator
    rfk = Relocator("http://localhost:8080/rfk","http://www.rfk.id.au/")
    goog = Relocator("http://localhost:8080/g","http://www.google.com/")
    svn = SVNRelocator("http://localhost:8080/svn","http://sphericalmatrix.com/svn/morph")
    if svn.matchesLocal(req.reqURI):
      return svn.mapping
    if rfk.matchesLocal(req.reqURI):
      return rfk.mapping
    if goog.matchesLocal(req.reqURI):
      return goog.mapping
    return None

def _demo():
    serve('',8080,_demo_mapper)

if __name__ == "__main__":
    _demo()

