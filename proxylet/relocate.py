"""

  proxylet.relocate:  relocate various http request/response types

Each relocator is a callable that takes a (req,resp) stream pair, and
returns a corresponding pair wrapped in the appropriate rewriting. We
provide a base Relocator class, as well as:

    * DAVRelocator:      WebDAV requests
    * SVNReloctaor:      Subversion requests
    * DrupalRelocator:   Fix some absolute URLs produced by Drupal

Each relocator is constructed with two arguments, the local root URL and
the corresponding remote root URL.  To aid in DRY, it provides some methods
for building a mapper function without repeating the URL info.

Here is an example of a simple mapper function, that sends all requests
to /svn/ to a backend SVN server:

    def mapper(req):
        r = SVNRelocator("http://www.example.com/svn","http://svn.example.com")
        if r.matchesLocal(req.reqURI):
           return r.mapping
        return ("www.example.com","80",None)

"""

from paste import httpheaders as hdr
from urlparse import *
import re
try:
  from cStringIO import StringIO
except ImportError:
  from StringIO import StringIO

from streams import HTTPRewriter, XMLRewriter

## Make a "Destination' header handler, since we
## need to rewrite it in WebDAV requests.
cmt = "RFC 2518, 9.3"
hdr.DESTINATION = hdr._SingleValueHeader("Destination","request",cmt,"1.1")
hdr.DESTINATION.__doc__ = cmt
del cmt


class UrlInfo(object):
    def __init__(self,url):
        if url[-1] == "/":
          url = url[0:-1]
        info = urlparse(url)
        self.url = url
        self.path = info.path or "/"
        self.baseurl = "%s://%s" % (info.scheme,info.netloc)
        self.port = info.port
        self.host = info.hostname
        self.scheme = info.scheme


class Relocator(object):
    """Base class for request/response relocator objects.
    This class takes care of basic header rewriting for relocation.
    Subclasses should implement the inner classes RewriteRequest
    and RewriteResponse as subclasses of HTTPRewriter to provide additional
    functionality.
    """

    def __init__(self,localRoot,remoteRoot):
        self.local = UrlInfo(localRoot)
        self.remote = UrlInfo(remoteRoot)
        port = self.remote.port
        if not port:
          if self.remote.scheme.lower() == "http":
            port = "80"
          if self.remote.scheme.lower() == "https":
            port = "443"
        self.mapping = (self.remote.host,port,self)

    def rewriteRemote(self,url):
        return self._rewrite(url,self.remote,self.local)

    def rewriteLocal(self,url):
        return self._rewrite(url,self.local,self.remote)

    def matchesLocal(self,url):
        return self._matches(url,self.local)

    def matchesRemote(self,url):
        return self._matches(url,self.remote)

    def _matches(self,url,info):
        # Try with full url matching
        if url.startswith(info.url):
            return True
        # Try with path matching
        if url.startswith(info.path):
            return True
        # Try host matching
        if url == info.host:
            return True
        return False

    def _rewrite(self,url,inU,outU):
        # Try with full url matching
        if url.startswith(inU.url):
            path = url[len(inU.url):]
            if path == "" or path[0] == "/":
                return outU.url + path
        # Try with path matching
        if url.startswith(inU.path):
            path = url[len(inU.path):]
            if path == "" or path[0] == "/":
                return outU.path + path
        # Try host matching
        if url == inU.host:
            return outU.host
        return url

    def __call__(self,req,resp):
        req2 = self.RewriteRequest(req,self)
        resp2 = self.RewriteResponse(resp,req,self)
        return (req2,resp2)

    class RewriteRequest(HTTPRewriter):
        def __init__(self,req,parent):
            HTTPRewriter.__init__(self,req)
            self.parent = parent

        def rwHeaders(self,headers):
            dest = hdr.DESTINATION(headers)
            if dest:
              hdr.DESTINATION.update(headers,self.parent.rewriteLocal(dest))
            hdr.HOST.update(headers,self.parent.remote.host)
            self.stream.reqURI = self.parent.rewriteLocal(self.stream.reqURI)

    class RewriteResponse(HTTPRewriter):
        def __init__(self,resp,req,parent):
            HTTPRewriter.__init__(self,resp)
            self.parent = parent
            self.request = req

        def rwHeaders(self,headers):
            loc = hdr.LOCATION(headers)
            if loc:
              hdr.LOCATION.update(headers,self.parent.rewriteRemote(loc))
            # TODO: rewriting of cookie data


def _checkContentType(headers,ctype):
    ct = hdr.CONTENT_TYPE(headers)
    if ct and ';' in ct:
      ct = ct.split(';',1)[0]
    return (ct == ctype)


class DAVRelocator(Relocator):
    """Relocate WebDAV requests."""

    # The methods for which we perform re-writing.
    # Re-writing e.g. GET requests could be very dangerous
    _filter_methods = {"OPTIONS": 1, "PROPFIND": 1, "REPORT": 1,
                       "MKACTIVITY": 1, "PROPPATCH": 1, "CHECKOUT": 1,
                       "MKCOL": 1, "MOVE": 1, "COPY": 1, "LOCK": 1,
                       "UNLOCK": 1, "MERGE": 1}

    class RewriteRequest(Relocator.RewriteRequest):
        def rwBody(self,bodyIn):
            if self.stream.reqMethod.upper() not in self.parent._filter_methods:
              return bodyIn
            if hdr.CONTENT_LENGTH(self.stream.headers) in (None,"","0"):
              return bodyIn
            bodyOut = XMLRewriter(bodyIn)
            bodyOut.rewrite = self.parent.rewriteLocal
            bodyOut.rw_content["D:href"] = True
            return bodyOut

    class RewriteResponse(Relocator.RewriteResponse):
        def rwBody(self,bodyIn):
           if self.request.reqMethod.upper() not in self.parent._filter_methods:
             return bodyIn
           if not _checkContentType(self.stream.headers,"text/xml"):
             return bodyIn 
           bodyOut = XMLRewriter(bodyIn)
           bodyOut.rewrite = self.parent.rewriteRemote
           bodyOut.rw_content["D:href"] = True
           return bodyOut


class SVNRelocator(Relocator):
    """Relocate Subversion web server requests."""

    # The methods for which we perform re-writing.
    # Re-writing e.g. GET requests could be very dangerous
    _filter_methods = {"OPTIONS": 1, "PROPFIND": 1, "REPORT": 1,
                       "MKACTIVITY": 1, "PROPPATCH": 1, "CHECKOUT": 1,
                       "MKCOL": 1, "MOVE": 1, "COPY": 1, "LOCK": 1,
                       "UNLOCK": 1, "MERGE": 1}

    class RewriteRequest(Relocator.RewriteRequest):
        def rwBody(self,bodyIn):
            if self.stream.reqMethod.upper() not in self.parent._filter_methods:
              return bodyIn
            if hdr.CONTENT_LENGTH(self.stream.headers) in (None,"","0"):
              return bodyIn
            bodyOut = XMLRewriter(bodyIn)
            bodyOut.rewrite = self.parent.rewriteLocal
            bodyOut.rw_content["D:href"] = True
            bodyOut.rw_content["S:src-path"] = True
            return bodyOut

    class RewriteResponse(Relocator.RewriteResponse):
        def rwBody(self,bodyIn):
           if self.request.reqMethod.upper() not in self.parent._filter_methods:
             return bodyIn
           if not _checkContentType(self.stream.headers,"text/xml"):
             return bodyIn 
           bodyOut = XMLRewriter(bodyIn)
           bodyOut.rewrite = self.parent.rewriteRemote
           bodyOut.rw_content["D:href"] = True
           bodyOut.rw_attrs["S:add-directory"] = {"bc-url": True}
           return bodyOut


class DrupalRelocator(Relocator):
    """Relocating simple HTML documents produced by Drupal.
    We don't try to be too clever about this - no hunting for URLs
    in scripts, css, etc.  We don't intend to serve applications
    that were written to belong under a different path, simply to
    work around broken apps that insist on generating absolute
    paths.
    """

    class RewriteResponse(Relocator.RewriteResponse):
        def rwBody(self,bodyIn):
          if not _checkContentType(self.stream.headers,"text/html"):
            return bodyIn
          data = []
          for ln in bodyIn:
            data.append(ln)
          data = "".join(data)
          repl = re.compile(r"""<form action="%s([^"]*)"([^>]*)>""" % (self.parent.remote.path,))
          data = repl.sub(r"""<form action="%s\1"\2>""" % (self.parent.local.path,),data)
          return StringIO(data)



