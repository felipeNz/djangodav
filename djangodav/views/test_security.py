import os
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import SimpleTestCase, RequestFactory, override_settings

from djangodav.fs.resources import BaseFSDavResource
from djangodav.views import DavView
from djangodav.utils import rfc5987_content_disposition
from djangodav.acls import FullAcl
from djangodav.locks import DummyLock
from djangodav.base.tests.resources import MockObject, MockCollection


class SecurityTests(SimpleTestCase):
    def relocation(self, destination='/dav/target', denied=None):
        source = MockObject('/source', get_descendants=Mock(return_value=[]), copy=Mock())
        parent = MockCollection('/parent/')
        target = MockObject('/target', get_parent=Mock(return_value=parent),
                            get_descendants=Mock(return_value=[]), delete=Mock())
        request = RequestFactory().generic('COPY', '/dav/source',
                    HTTP_DESTINATION='http://testserver' + destination)
        view = DavView(request=request, base_url='/dav/', acl_class=FullAcl,
                       lock_class=DummyLock, resource_class=Mock(return_value=target))
        view.__dict__['resource'] = source
        view.has_access = lambda resource, permission: (resource, permission) != denied
        return view, request, source, target, parent

    def test_copy_denied_destination_is_not_deleted(self):
        view, request, source, target, parent = self.relocation()
        view.has_access = lambda resource, permission: resource is not parent
        self.assertEqual(view.copy(request, '/source', None).status_code, 403)
        target.delete.assert_not_called()
        source.copy.assert_not_called()

    def test_copy_outside_mount_is_rejected(self):
        view, request, source, target, parent = self.relocation('/other/target')
        self.assertEqual(view.copy(request, '/source', None).status_code, 400)
        target.delete.assert_not_called()

    def test_copy_overlapping_path_is_rejected(self):
        view, request, source, target, parent = self.relocation()
        target.path = ['source', 'child']
        self.assertEqual(view.copy(request, '/source', None).status_code, 403)
        target.delete.assert_not_called()

    def test_unreadable_collection_is_not_traversed(self):
        hidden = MockCollection('/hidden/', get_children=Mock())
        root = MockCollection('/', get_children=Mock(return_value=[hidden]))
        view = DavView()
        view.has_access = lambda resource, permission: resource is not hidden
        self.assertEqual(list(view.readable_descendants(root, -1)), [root])
        hidden.get_children.assert_not_called()

    def test_recursive_delete_preflights_child_permissions(self):
        child = MockObject('/folder/private')
        root = MockCollection('/folder/', get_descendants=Mock(return_value=[child]), delete=Mock())
        view = DavView(lock_class=DummyLock)
        view.__dict__['resource'] = root
        view.has_access = lambda resource, permission: resource is not child
        self.assertEqual(view.delete(RequestFactory().delete('/folder/'), '/folder/').status_code, 403)
        root.delete.assert_not_called()

    def test_filesystem_rejects_unsafe_paths(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as root:
            class Resource(BaseFSDavResource):
                pass
            Resource.root = root
            for path in ('../outside', 'a/../../outside', 'C:/outside',
                         'a\\..\\outside', 'file:stream', 'name.', 'name '):
                with self.subTest(path=path), self.assertRaises(PermissionDenied):
                    Resource(path).get_abs_path()
            self.assertEqual(Resource('safe/file').get_abs_path(), os.path.join(os.path.realpath(root), 'safe', 'file'))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory(dir=os.getcwd()) as root:
            class Resource(BaseFSDavResource):
                pass
            Resource.root = root
            try:
                os.symlink(root, os.path.join(root, 'cycle'), target_is_directory=True)
            except OSError:
                self.skipTest('Symlink creation unavailable')
            with self.assertRaises(PermissionDenied):
                Resource('cycle').get_abs_path()

    def test_junction_rejected(self):
        class Resource(BaseFSDavResource):
            root = os.getcwd()
        with patch('djangodav.fs.resources.os.path.isjunction', return_value=True):
            with self.assertRaises(PermissionDenied):
                Resource('junction').get_abs_path()

    def test_xml_errors_return_bad_request(self):
        for body in (b'<broken', b'<!DOCTYPE x [<!ENTITY a "x">]><x>&a;</x>'):
            request = RequestFactory().generic('PROPFIND', '/dav/', body, content_type='application/xml')
            view = DavView(request=request)
            self.assertEqual(view.dispatch(request, '').status_code, 400)

    @override_settings(DJANGODAV_MAX_XML_BYTES=8)
    def test_xml_size_limit(self):
        request = RequestFactory().generic('PROPFIND', '/dav/', b'<longbody/>', content_type='application/xml')
        self.assertEqual(DavView(request=request).dispatch(request, '').status_code, 413)

    def test_session_csrf_cannot_be_bypassed_with_authorization_header(self):
        request = RequestFactory().put('/dav/file', b'changed', HTTP_AUTHORIZATION='garbage')
        request.user = SimpleNamespace(is_authenticated=True)
        handler = Mock(return_value=HttpResponse())
        view = DavView(request=request, put=handler)
        self.assertEqual(view.dispatch(request, 'file').status_code, 403)
        handler.assert_not_called()

    def test_content_disposition_escapes_filename(self):
        value = rfc5987_content_disposition('bad"; filename="attack\r\n.txt')
        self.assertNotIn('\r', value)
        self.assertNotIn('\n', value)
        self.assertIn('bad\\"; filename=\\"attack.txt', value)
