# Refactoring, Django 1.11 compatibility, cleanups, bugfixes (c) 2018 Christian Kreuzberger <ckreuzberger@anexia-it.com>
# All rights reserved.
#
# Portions (c) 2014, Alexander Klimenko <alex@erix.ru>
# All rights reserved.
#
# Copyright (c) 2011, SmartFile <btimby@smartfile.com>
# All rights reserved.
#
# This file is part of DjangoDav.
#
# DjangoDav is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# DjangoDav is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with DjangoDav.  If not, see <http://www.gnu.org/licenses/>.
import datetime
import os
import shutil
from sys import getfilesystemencoding
from django.core.exceptions import PermissionDenied

from djangodav.base.resources import BaseDavResource
from djangodav.utils import url_join

fs_encoding = getfilesystemencoding()


class BaseFSDavResource(BaseDavResource):
    """Implements an interface to the file system. This can be subclassed to provide
    a virtual file system (like say in MySQL). This default implementation simply uses
    python's os library to do most of the work."""

    root = None
    quote = False

    def get_abs_path(self):
        """Return the absolute path of the resource. Used internally to interface with
        an actual file system. If you override all other methods, this one will not
        be used."""
        root = os.path.realpath(self.root)
        for part in self.path:
            if (part in ('.', '..') or any(c in part for c in ('\\', ':', '\x00'))
                    or part.endswith((' ', '.'))):
                raise PermissionDenied('Invalid resource path')
            if os.name == 'nt' and os.path.isreserved(part):
                raise PermissionDenied('Reserved resource path')
        path = os.path.join(root, *self.path)
        resolved = os.path.realpath(path)
        try:
            contained = os.path.commonpath((root, resolved)) == root
        except ValueError:
            contained = False
        if not contained:
            raise PermissionDenied('Resource outside DAV root')
        # Reject links within the root too: directory links can form cycles.
        current = root
        for part in self.path:
            current = os.path.join(current, part)
            if os.path.islink(current) or os.path.isjunction(current):
                raise PermissionDenied('Linked resources are not supported')
        return path

    @property
    def getcontentlength(self):
        """Return the size of the resource in bytes."""
        return os.path.getsize(self.get_abs_path())

    def get_created(self):
        """Return the create time as datetime object."""
        return datetime.datetime.fromtimestamp(os.stat(self.get_abs_path()).st_ctime)

    def get_modified(self):
        """Return the modified time as datetime object."""
        return datetime.datetime.fromtimestamp(os.stat(self.get_abs_path()).st_mtime)

    @property
    def is_collection(self):
        """Return True if this resource is a directory (collection in WebDAV parlance)."""
        return os.path.isdir(self.get_abs_path())

    @property
    def is_object(self):
        """Return True if this resource is a file (resource in WebDAV parlance)."""
        return os.path.isfile(self.get_abs_path())

    @property
    def exists(self):
        """Return True if this resource exists."""
        return os.path.exists(self.get_abs_path())

    def get_children(self):
        """Return an iterator of all direct children of this resource."""
        # make sure the current object is a directory
        path = self.get_abs_path()

        if os.path.isdir(path):
            for child in os.listdir(path):
                try:
                    is_unicode = isinstance(child, str)
                except NameError:  # Python 3 fix
                    is_unicode = isinstance(child, str)
                if not is_unicode:
                    child = child.decode(fs_encoding)
                yield self.clone(url_join(*(self.path + [child])))

    def write(self, content, temp_file=None, range_start=None):
        raise NotImplementedError

    def read(self):
        raise NotImplementedError

    def delete(self):
        """Delete the resource, recursive is implied."""
        if self.is_collection:
            for child in self.get_children():
                child.delete()
            os.rmdir(self.get_abs_path())
        elif self.is_object:
            os.remove(self.get_abs_path())

    def create_collection(self):
        """Create a directory in the location of this resource."""
        os.mkdir(self.get_abs_path())

    def copy_object(self, destination, depth=0):
        shutil.copy(self.get_abs_path(), destination.get_abs_path())

    def move_object(self, destination):
        os.rename(self.get_abs_path(), destination.get_abs_path())


class DummyReadFSDavResource(BaseFSDavResource):
    def read(self):
        return open(self.get_abs_path(), 'rb')


class DummyWriteFSDavResource(BaseFSDavResource):
    """
    Provides a "dummy" write method for FS Dav Resources
    """
    def write(self, request, temp_file=None, range_start=None):
        if temp_file:
            # move temp file (e.g., coming from nginx)
            shutil.move(temp_file, self.get_abs_path())
        elif range_start == None:
            # open binary file and write to disk
            with open(self.get_abs_path(), 'wb') as dst:
                shutil.copyfileobj(request, dst)
        else:
            # open binary file and write to disk
            with open(self.get_abs_path(), 'r+b') as dst:
                dst.seek(range_start)
                shutil.copyfileobj(request, dst)

class DummyFSDAVResource(DummyReadFSDavResource, DummyWriteFSDavResource, BaseFSDavResource):
    pass
