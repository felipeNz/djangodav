import os
import re
from collections import OrderedDict
from xml.etree import ElementTree

# import urllib.parse
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import router, transaction

try:
    # Python 2.7
    import urlparse
except ImportError:
    # Python 3
    from urllib import parse as urlparse

from defusedxml.ElementTree import parse

from django.conf import settings
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, HttpResponseBadRequest, \
    HttpResponseRedirect, Http404, HttpResponse, FileResponse
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
#from django.utils.http import urlquote
from urllib.parse import quote
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from djangodav.responses import HttpResponsePreconditionFailed, HttpResponseCreated, HttpResponseNoContent, \
    HttpResponseConflict, HttpResponseMediatypeNotSupported, HttpResponseBadGateway, HttpResponseMultiStatus, \
    HttpResponseLocked, ResponseException
from djangodav.models import DeadProperty
from djangodav.utils import D, WEBDAV_NS, url_join, get_property_tag_list, rfc1123_date, \
    rfc5987_content_disposition, serialize_xml, local_name, findall_dav, find_dav


PATTERN_IF_DELIMITER = re.compile(r'(<([^>]+)>)|(\(([^\)]+)\))')
PATTERN_CONTENT_RANGE=re.compile('^\s*bytes\s*([0-9]*)-.*$')
# get settings
DJANGODAV_X_REDIRECT = getattr(settings, 'DJANGODAV_X_REDIRECT', None)
DJANGODAV_X_REDIRECT_PREFIX = getattr(settings, 'DJANGODAV_X_REDIRECT_PREFIX', "")


class DavView(TemplateView):
    """
    Basic WebDav View, providing the necessary endpoints for accessing WebDav via a Browser aswell as a File Explorer
    """
    resource_class = None
    lock_class = None
    acl_class = None
    template_name = 'djangodav/index.html'
    http_method_names = ['options', 'put', 'mkcol', 'head', 'get', 'delete', 'propfind', 'proppatch', 'copy', 'move', 'lock', 'unlock']
    server_header = 'DjangoDav'

    xml_pretty_print = False
    xml_encoding = 'utf-8'
    property_scope = None

    def no_access(self):
        return HttpResponseForbidden()

    @method_decorator(csrf_exempt)
    def dispatch(self, request, path, *args, **kwargs):
        """
        Basic dispatch handler for all requests coming to the
        :param request:
        :param path:
        :param args:
        :param kwargs:
        :return:
        """
        if path:
            self.path = path
            self.base_url = request.META['PATH_INFO'][:-len(self.path)]
        else:
            self.path = '/'
            self.base_url = request.META['PATH_INFO']

        meta = request.META.get
        self.xbody = kwargs['xbody'] = None
        if (request.method.lower() != 'put'
            and "/xml" in meta('CONTENT_TYPE', '')
            and meta('CONTENT_LENGTH', 0) != ''
            and int(meta('CONTENT_LENGTH', 0)) > 0):

            # parse XML using defusedxmls parse function
            self.xbody = kwargs['xbody'] = parse(request).getroot()

        if request.method.upper() in self._allowed_methods():
            handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
        else:
            handler = self.http_method_not_allowed
        try:
            resp = handler(request, self.path, *args, **kwargs)
        except ResponseException as e:
            print(e)
            resp = e.response
        except PermissionDenied as pe:
            print(pe)
            resp = HttpResponseForbidden()
        except ValidationError as ve:
            print(ve)
            resp = HttpResponseBadRequest()

        if not 'Allow' in resp:
            methods = self._allowed_methods()
            if methods:
                resp['Allow'] = ", ".join(methods)
        if not 'Date' in resp:
            resp['Date'] = rfc1123_date(now())
        if self.server_header:
            resp['Server'] = self.server_header
        return resp

    def options(self, request, path, *args, **kwargs):
        if not self.has_access(self.resource, 'read'):
            return self.no_access()
        response = self.build_xml_response()
        response['DAV'] = '1,2'
        response['Content-Length'] = '0'
        if self.path in ('/', '*'):
            return response
        response['Allow'] = ", ".join(self._allowed_methods())
        if self.resource.exists and self.resource.is_object:
            response['Accept-Ranges'] = 'bytes'
        return response

    def _allowed_methods(self):
        allowed = [
            'HEAD', 'OPTIONS', 'PROPFIND', 'LOCK', 'UNLOCK',
            'GET', 'DELETE', 'PROPPATCH', 'COPY', 'MOVE', 'PUT', 'MKCOL',
        ]

        return allowed

    def get_access(self, resource):
        """Return permission as DavAcl object. A DavACL should have the following attributes:
        read, write, delete, create, relocate, list. By default we implement a read-only
        system."""
        return self.acl_class(read=True, full=False)

    def has_access(self, resource, method):
        return getattr(self.get_access(resource), method)

    def get_resource_kwargs(self, **kwargs):
        return kwargs

    @cached_property
    def resource(self):
        return self.get_resource(path=self.path)

    def get_property_scope(self):
        if self.property_scope is not None:
            return self.property_scope
        resource_class = self.resource_class or self.resource.__class__
        return '%s.%s' % (resource_class.__module__, resource_class.__qualname__)

    def get_dead_properties(self, resource):
        resource_key = DeadProperty.resource_key_for(
            self.get_property_scope(), resource.get_path()
        )
        alias = router.db_for_read(DeadProperty)
        return {
            prop.name: ElementTree.fromstring(prop.value)
            for prop in DeadProperty.objects.using(alias).filter(resource_key=resource_key)
        }

    def get_resource(self, **kwargs):
        return self.resource_class(**self.get_resource_kwargs(**kwargs))

    def get_depth(self, default='1'):
        depth = str(self.request.META.get('HTTP_DEPTH', default)).lower()
        if not depth in ('0', '1', 'infinity'):
            raise ResponseException(HttpResponseBadRequest('Invalid depth header value %s' % depth))
        if depth == 'infinity':
            depth = -1
        else:
            depth = int(depth)
        return depth

    def get_context_data(self, **kwargs):
        context = super(DavView, self).get_context_data(**kwargs)
        context['resource'] = self.resource
        context['base_url'] = self.base_url
        # build parent directory according to the current request
        context['parent_directory_url'] = self.request.build_absolute_uri("/".join(self.request.path.rstrip('/').split('/')[:-1]))
        return context

    def get(self, request, path, head=False, *args, **kwargs):
        """
        GET a resource

        If head=True, only the headers are returned

        This method also handles X-Accel-Redirect headers

        :param request:
        :param path:
        :param head:
        :param args:
        :param kwargs:
        :return:
        """
        if not self.resource.exists:
            # Resource does not exist
            if head:
                return HttpResponse(content='', status=404)
            raise Http404("Resource doesn't exists")
        if not path.endswith("/") and self.resource.is_collection:
            # make sure collections always end with a slash
            return HttpResponseRedirect(request.build_absolute_uri() + "/")
        if path.endswith("/") and self.resource.is_object:
            # make sure files do not end with a slash
            return HttpResponseRedirect(request.build_absolute_uri().rstrip("/"))

        # make sure the user has access
        if not self.has_access(self.resource, 'read'):
            return self.no_access()

        # construct a response
        response = FileResponse()

        # set default content length to 0 - we can still overwrite it later
        response['Content-Length'] = 0

        # it's either an object or a collection
        if self.resource.is_object:
            # is an object
            response['Content-Type'] = self.resource.content_type
            response['ETag'] = self.resource.etag
            response['Content-Length'] = self.resource.getcontentlength
            response['Accept-Ranges'] = 'bytes'
            response['Cache-Control'] = 'must-revalidate'
            
            etags = request.META.get('HTTP_IF_NONE_MATCH',None)
            if etags \
                and (self.resource.etag in (e.strip(' ').strip('"') for e in etags.split(','))):
                     response.status_code=304
                     return response
            if not head:
                # not a head request, so we can actually return a response
                if DJANGODAV_X_REDIRECT:
                    # Using X-Accel-Redirect
                    # create a new response that handles x-accel-redirect
                    response = HttpResponse()

                    # get the path to the requested file
                    current_path_to_file = self.resource.read().name

                    # make sure the path is relative
                    if current_path_to_file.startswith("/"):
                        # absolute path - convert it into a path relative to the resources root path
                        relpath = os.path.relpath(self.resource.read().name, self.resource.root)
                    else:
                        # it's already a relative path, everything is fine
                        relpath = self.resource.read().name

                    # we are not allowed to send utf8 headers, so we need to make sure to quote it
                    response['X-Accel-Redirect'] = quote(
                        # join url with the DAV prefix
                        url_join(DJANGODAV_X_REDIRECT_PREFIX, relpath)
                    )
                    # set the display name as the content disposition header, acting as the download name of the file
                    response['Content-Disposition'] = rfc5987_content_disposition(self.resource.displayname)
                    response['Content-Type'] = self.resource.content_type

                    # Unfortunately, setting content-length, last-modified and etag does not work with nginx, as those
                    # are overwritten by nginx, see https://forum.nginx.org/read.php?2,205636,205665#msg-205665
                    # Therefore we need to set them with a prefix, e.g., X-Accel-, and handle it with nginx
                    # add_header and $upstream_http_*
                    response['X-Accel-Content-Length'] = self.resource.getcontentlength
                    response['X-Accel-Last-Modified'] = self.resource.get_modified().ctime()
                    response['X-Accel-ETag'] = self.resource.etag

                    return response
                else:
                    # try to read the resource and return it in response
                    response.streaming_content = self.resource.read()
        elif not head:
            # not a head request, and not an object -> render index.html
            response = super(DavView, self).get(request, *args, **kwargs)

        # set last modified field of response, so browsers and other tools can properly handle caching
        response['Last-Modified'] = self.resource.getlastmodified

        return response

    def head(self, request, path, *args, **kwargs):
        """
        Return just the headers

        Calls the get function with head=True, so the get function knows to only return ehaders
        :param request:
        :param path:
        :param args:
        :param kwargs:
        :return:
        """
        return self.get(request, path, head=True, *args, **kwargs)

    def put(self, request, path, *args, **kwargs):
        """
        Upload a new file
        :param request:
        :param path:
        :param args:
        :param kwargs:
        :return:
        """
        parent = self.resource.get_parent()
        if not parent.exists:
            return HttpResponseConflict("Resource doesn't exists")
        if self.resource.is_collection:
            return HttpResponseNotAllowed(list(set(self._allowed_methods()) - set(['MKCOL', 'PUT'])))
        if not self.resource.exists and not self.has_access(parent, 'write'):
            return self.no_access()
        if self.resource.exists and not self.has_access(self.resource, 'write'):
            return self.no_access()
        created = not self.resource.exists

        # check headers for X-File-Name
        range = request.META.get('HTTP_CONTENT_RANGE', None)
        if range == None:
            range_start=None
        else:
            m=PATTERN_CONTENT_RANGE.match(range)
            if not m: return HttpResponseBadRequest("Invalid Content-Range")
            range_start=int(m[1])
            
        self.resource.write(request, range_start=range_start)

        if created:
            self.__dict__['resource'] = self.get_resource(path=self.resource.get_path())
            return HttpResponseCreated()
        else:
            return HttpResponseNoContent()

    def delete(self, request, path, *args, **kwargs):
        """
        Delete an element
        :param request:
        :param path:
        :param args:
        :param kwargs:
        :return:
        """
        if not self.resource.exists:
            raise Http404("Resource doesn't exists")
        if not self.has_access(self.resource, 'delete'):
            return self.no_access()
        self.lock_class(self.resource).del_locks()
        self.resource.delete()
        response = HttpResponseNoContent()
        self.__dict__['resource'] = self.get_resource(path=self.resource.get_path())
        return response

    def mkcol(self, request, path, *args, **kwargs):
        """
        Create a new collection (a directory)
        :param request:
        :param path:
        :param args:
        :param kwargs:
        :return:
        """
        if self.resource.exists:
            return HttpResponseNotAllowed(list(set(self._allowed_methods()) - set(['MKCOL', 'PUT'])))
        if not self.resource.get_parent().exists:
            return HttpResponseConflict()
        length = request.META.get('CONTENT_LENGTH', 0)
        if length and int(length) != 0:
            return HttpResponseMediatypeNotSupported()
        if not self.has_access(self.resource, 'write'):
            return self.no_access()
        self.resource.create_collection()
        self.__dict__['resource'] = self.get_resource(path=self.resource.get_path())
        return HttpResponseCreated()

    def relocate(self, request, path, method, *args, **kwargs):
        """
        Relocate an element

        Handles copying and moving of all sorts of elements
        :param request:
        :param path:
        :param method:
        :param args:
        :param kwargs:
        :return:
        """
        if not self.resource.exists:
            raise Http404("Resource doesn't exists")
        if not self.has_access(self.resource, 'read'):
            return self.no_access()
        # need to double unquote the HTTP_DESTINATION header (Windows 7 Compatibility)
        dst = urlparse.unquote(urlparse.unquote(request.META.get('HTTP_DESTINATION', '')))  # .decode(self.xml_encoding)
        if not dst:
            return HttpResponseBadRequest('Destination header missing.')

        original_dst = dst

        dparts = urlparse.urlparse(dst)
        sparts = urlparse.urlparse(request.build_absolute_uri())
        if sparts.scheme != dparts.scheme or sparts.hostname != dparts.hostname:
            return HttpResponseBadGateway('Source and destination must have the same scheme and host.')
        # adjust path for our base url:
        dst = self.get_resource(path=dparts.path[len(self.base_url):])
        if not dst.get_parent().exists:
            return HttpResponseConflict()
        if not self.has_access(self.resource, 'write'):
            return self.no_access()
        overwrite = request.META.get('HTTP_OVERWRITE', 'T')
        if overwrite not in ('T', 'F'):
            return HttpResponseBadRequest('Overwrite header must be T or F.')
        overwrite = (overwrite == 'T')
        if not overwrite and dst.exists:
            return HttpResponsePreconditionFailed('Destination exists and overwrite False.')
        dst_exists = dst.exists
        if dst_exists:
            self.lock_class(self.resource).del_locks()
            self.lock_class(dst).del_locks()
            dst.delete()
        errors = getattr(self.resource, method)(dst, *args, **kwargs)
        if errors:
            print(errors)
            return self.build_xml_response(response_class=HttpResponseMultiStatus) # WAT?
        if dst_exists:
            return HttpResponseNoContent()

        # return a response with the new location
        response = HttpResponseCreated()
        response['Location'] = original_dst
        return response

    def copy(self, request, path, xbody):
        """
        Copy an element
        :param request:
        :param path: full path of the element that is about to be copied
        :param xbody:
        :return:
        """
        depth = self.get_depth()
        # if depth != -1:
        #     print("canceling because depth=", depth)
        #     return HttpResponseBadRequest()

        print("Copying {} located at {} to ...".format(self.resource.displayname, path))

        return self.relocate(request, path, 'copy', depth=depth)

    def move(self, request, path, xbody):
        """
        Move an element
        :param request:
        :param path: full path of the element that is about to be moved
        :param xbody:
        :return:
        """
        if not self.has_access(self.resource, 'delete'):
            return self.no_access()
        return self.relocate(request, path, 'move')

    def lock(self, request, path, xbody=None, *args, **kwargs):
        # TODO Lock refreshing
        if not self.has_access(self.resource, 'write'):
            return self.no_access()

        if not xbody:
            return HttpResponseBadRequest('Lockinfo required')

        try:
            depth = int(request.META.get('HTTP_DEPTH', '0'))
        except ValueError:
            return HttpResponseBadRequest('Wrong depth')

        try:
            timeout = int(request.META.get('HTTP_LOCK_TIMEOUT', 'Seconds-600')[len('Seconds-'):])
        except ValueError:
            return HttpResponseBadRequest('Wrong timeout')

        owner = None
        owner_obj = find_dav(xbody, 'D:lockinfo/D:owner')
        if owner_obj is not None:
            if owner_obj.text:
                owner = owner_obj.text
            if len(owner_obj):
                owner = owner_obj[0].text

        lockscope_obj = find_dav(xbody, 'D:lockinfo/D:lockscope/*')
        if lockscope_obj is None:
            return HttpResponseBadRequest('Lock scope required')
        lockscope = local_name(lockscope_obj)

        locktype_obj = find_dav(xbody, 'D:lockinfo/D:locktype/*')
        if locktype_obj is None:
            return HttpResponseBadRequest('Lock type required')
        locktype = local_name(locktype_obj)

        token = self.lock_class(self.resource).acquire(lockscope, locktype, depth, timeout, owner)
        if not token:
            return HttpResponseLocked('Already locked')

        body = D.activelock(*([
            D.locktype(locktype_obj),
            D.lockscope(lockscope_obj),
            D.depth(str(depth)),
            D.timeout("Second-%s" % timeout),
            D.locktoken(D.href('opaquelocktoken:%s' % token))]
            + ([owner_obj] if owner_obj is not None else [])
        ))

        return self.build_xml_response(body)

    def unlock(self, request, path, xbody=None, *args, **kwargss):
        if not self.has_access(self.resource, 'write'):
            return self.no_access()

        token = request.META.get('HTTP_LOCK_TOKEN')
        if not token:
            return HttpResponseBadRequest('Lock token required')
        if not self.lock_class(self.resource).release(token):
            return self.no_access()
        return HttpResponseNoContent()

    def propfind(self, request, path, xbody=None, *args, **kwargs):
        if not self.has_access(self.resource, 'read'):
            return self.no_access()

        if not self.resource.exists:
            raise Http404("Resource doesn't exists")

        if not self.get_access(self.resource):
            return self.no_access()

        get_all_props, get_prop, get_prop_names = True, False, False
        if xbody:
            get_prop = [p.tag for p in findall_dav(xbody, 'D:propfind/D:prop/*')]
            get_all_props = findall_dav(xbody, 'D:propfind/D:allprop')
            get_prop_names = findall_dav(xbody, 'D:propfind/D:propname')
            if int(bool(get_prop)) + int(bool(get_all_props)) + int(bool(get_prop_names)) != 1:
                return HttpResponseBadRequest()

        children = self.resource.get_descendants(depth=self.get_depth())

        responses = []
        for child in children:
            dead_properties = self.get_dead_properties(child)
            live_names = ['{%s}%s' % (WEBDAV_NS, name) for name in child.ALL_PROPS]
            requested_names = get_prop if get_prop else live_names + list(dead_properties)
            found = []
            missing = []
            for name in requested_names:
                if name in dead_properties:
                    prop = dead_properties[name]
                    found.append(ElementTree.Element(prop.tag) if get_prop_names else prop)
                elif name.startswith('{%s}' % WEBDAV_NS):
                    live_name = name.split('}', 1)[1]
                    if live_name in child.ALL_PROPS:
                        prop = get_property_tag_list(child, live_name)
                        if prop:
                            found.append(
                                ElementTree.Element(name) if get_prop_names else prop[0]
                            )
                        elif get_prop:
                            missing.append(ElementTree.Element(name))
                    else:
                        missing.append(ElementTree.Element(name))
                else:
                    missing.append(ElementTree.Element(name))

            propstats = []
            if found:
                propstats.append(D.propstat(
                    D.prop(*found),
                    D.status('HTTP/1.1 200 OK'),
                ))
            if missing:
                propstats.append(D.propstat(
                    D.prop(*missing),
                    D.status('HTTP/1.1 404 Not Found'),
                ))
            responses.append(D.response(
                D.href(url_join(self.base_url, child.get_escaped_path())),
                *propstats
            ))

        body = D.multistatus(*responses)
        return self.build_xml_response(body, HttpResponseMultiStatus)

    def proppatch(self, request, path, xbody, *args, **kwargs):
        if not self.resource.exists:
            raise Http404("Resource doesn't exists")
        if not self.has_access(self.resource, 'write'):
            return self.no_access()
        depth = self.get_depth(default="0")
        if depth != 0:
            return HttpResponseBadRequest('Invalid depth header value %s' % depth)
        dav_propertyupdate = '{%s}propertyupdate' % WEBDAV_NS
        dav_set = '{%s}set' % WEBDAV_NS
        dav_remove = '{%s}remove' % WEBDAV_NS
        dav_prop = '{%s}prop' % WEBDAV_NS
        if xbody is None or xbody.tag != dav_propertyupdate:
            return HttpResponseBadRequest('A DAV:propertyupdate body is required.')

        instructions = []
        for instruction in list(xbody):
            if instruction.tag not in (dav_set, dav_remove) or len(instruction) != 1:
                return HttpResponseBadRequest('Invalid PROPPATCH instruction.')
            properties = instruction[0]
            if properties.tag != dav_prop or not len(properties):
                return HttpResponseBadRequest('Each instruction requires DAV:prop properties.')
            operation = 'set' if instruction.tag == dav_set else 'remove'
            for prop in properties:
                if not isinstance(prop.tag, str):
                    return HttpResponseBadRequest('Invalid property name.')
                instructions.append((operation, prop))

        if not instructions:
            return HttpResponseBadRequest('At least one property instruction is required.')

        protected = set(self.resource.LIVE_PROPERTIES)
        failed = any(
            prop.tag in protected or
            (prop.tag.startswith('{%s}' % WEBDAV_NS) and
             prop.tag.split('}', 1)[1] in self.resource.ALL_PROPS)
            for _, prop in instructions
        )
        statuses = OrderedDict()
        if failed:
            for _, prop in instructions:
                status = 403 if (
                    prop.tag in protected or
                    (prop.tag.startswith('{%s}' % WEBDAV_NS) and
                     prop.tag.split('}', 1)[1] in self.resource.ALL_PROPS)
                ) else 424
                statuses.setdefault(status, []).append(ElementTree.Element(prop.tag))
        else:
            scope = self.get_property_scope()
            path = self.resource.get_path()
            resource_key = DeadProperty.resource_key_for(scope, path)
            alias = router.db_for_write(DeadProperty)
            with transaction.atomic(using=alias):
                for operation, prop in instructions:
                    key = DeadProperty.key_for(scope, path, prop.tag)
                    if operation == 'set':
                        DeadProperty.objects.using(alias).update_or_create(
                            key=key,
                            defaults={
                                'resource_key': resource_key,
                                'scope': scope,
                                'path': path,
                                'name': prop.tag,
                                'value': ElementTree.tostring(prop, encoding='unicode'),
                            },
                        )
                    else:
                        DeadProperty.objects.using(alias).filter(key=key).delete()
            statuses[200] = [ElementTree.Element(prop.tag) for _, prop in instructions]

        status_text = {
            200: 'OK',
            403: 'Forbidden',
            424: 'Failed Dependency',
        }
        propstats = [
            D.propstat(
                D.prop(*props),
                D.status('HTTP/1.1 %d %s' % (status, status_text[status])),
            )
            for status, props in statuses.items()
        ]
        body = D.multistatus(D.response(
            D.href(url_join(self.base_url, self.resource.get_escaped_path())),
            *propstats
        ))
        return self.build_xml_response(body, HttpResponseMultiStatus)

    def build_xml_response(self, tree=None, response_class=HttpResponse, **kwargs):
        if tree is not None:
            content = serialize_xml(tree, pretty_print=self.xml_pretty_print, encoding=self.xml_encoding)
        else:
            content = b''
        return response_class(
            content,
            content_type='text/xml; charset="%s"' % self.xml_encoding,
            **kwargs
        )
