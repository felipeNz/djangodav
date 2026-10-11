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
from hashlib import sha256

from django.db import models


class DeadProperty(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    resource_key = models.CharField(max_length=64, db_index=True)
    scope = models.TextField()
    path = models.TextField()
    name = models.TextField()
    value = models.TextField()

    @staticmethod
    def resource_key_for(scope, path):
        identity = '%s\0%s' % (scope, path)
        return sha256(identity.encode('utf-8')).hexdigest()

    @classmethod
    def key_for(cls, scope, path, name):
        identity = '%s\0%s' % (cls.resource_key_for(scope, path), name)
        return sha256(identity.encode('utf-8')).hexdigest()
