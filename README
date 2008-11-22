
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

