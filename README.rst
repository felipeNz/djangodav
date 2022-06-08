DjangoDav
=========

Production ready WebDav extension for Django.

.. image:: https://travis-ci.org/anx-ckreuzberger/djangodav.svg

Motivation
----------

Django is a very popular tool which provides data representation and management. One of the key goals is to provide
machine access to it. Most popular production ready tools provide json based api access. Which have their own
advantages and disadvantages.

WebDav today is a standard for cooperative document management. Its clients are built in the modern operation systems
and supported by the world popular services. But it is very important to remember that it's not only about file storage,
WebDab provides a set of methods to deal with tree structured objects of any kind.

Providing WebDav access to Django resources opens new horizons for building Web2.0 apps, with inplace edition and
providing native operation system access to the stored objects.


Example App
-----------

An example app is provided `at another repository <https://github.com/anx-ckreuzberger/djangodav-example-app>`_.

For a quick example please look at the code at the bottom of this readme.


Development & Contributions
---------------------------

- Create a virtual environment: ``virtualenv -p python3 env``
- Activate virtual environment: ``source env/bin/activate``
- Install dependencies: ``pip install requirements.txt``
- Edit Source Code and make a Pull Request :)


Contributions within this repository
------------------------------------

- Cleanup
- Django 1.11+ compatibility
- Python3 compatibility
- Replaced `vulnerable lxml.etree.parse function <https://blog.python.org/2013/02/announcing-defusedxml-fixes-for-xml.html>`_ with ``defusedxml.lxml.parse``
- Documentation
- Pep8/Pycodestyle fixes


Original Source
---------------

The original source code is from the following repositories

- `djangodav by TZanke <https://github.com/TZanke/djangodav>`_
- `djangodav by MnogoByte <https://github.com/MnogoByte/djangodav>`_
- `django-webdav by sirmmo <https://github.com/sirmmo/django-webdav>`_



Difference with SmartFile django-webdav
---------------------------------------

Base resource functionality was separated into BaseResource class from the storage
functionality which developers free to choose from provided or implement themselves.

Improved class dependencies. Resource class don’t know anything about url or server, its
goal is only to store content and provide proper access.

Removed properties helper class. View is now responsible for xml generation, and resource
provides actual property list.

Server is now inherited from Django Class Based View, and renamed to DavView.

Key methods covered with tests.

Removed redundant request handler.

Added FSResource and DBResource to provide file system and data base access.

Xml library usage is replaced with lxml to achieve proper xml generation code readability.


Known Issues / Limitations
--------------------------

Basic Authentication on Windows
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Be careful when using Basic Authentication on Windows, as it is not enabled by default (for non SSL sites). You can
either set ``BasicAuthLevel`` to ``2`` in the `Windows Registry <http://www.windowspage.de/tipps/022703.html>`_ , or
just make sure your site uses SSL and has a valid SSL certificate.


File Size Limit of 47 MB on Windows (Error 0x800700DF)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Windows enforces a 47 MB limit on WebDav files. See `this issue on Microsoft Answers <https://answers.microsoft.com/en-us/ie/forum/ie8-windows_xp/error-0x800700df-the-file-size-exceeds-the-limit/d208bba6-920c-4639-bd45-f345f462934f>`_ 
aswell as `this issue on StackExchange <https://sharepoint.stackexchange.com/questions/119302/error-0x800700df-the-file-size-exceeds-the-limit-allowed-and-cannot-be-saved>`_.
It can be fixed by increasing the registry parameter ``FileSizeLimitInBytes`` in ``HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\WebClient\Parameters`` to ``4294967295``.

Another way to fix this issue is using a dedicated WebDav client for Windows, such as `RaiDrive <https://www.raidrive.com/>`_.

Examples / Getting started
--------------------------

1. Install ``djangodav`` from this repo: ``pip install git+https://github.com/felipeNz/djangodav``

2. Add ``djangodav`` and ``rest_framework`` to your ``INSTALLED_APPS``:

.. code-block:: python

    INSTALLED_APPS = [
        ...
        # djangodav
        'djangodav',
        # rest_framework neeeds to be here for templates
        'rest_framework',
    ]


Example 1: Create a simple filesystem webdav resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This will just host the provided directory ``/path/to/folder``, without any permission handling.

1. Create resources.py

.. code:: python

    from djangodav.base.resources import MetaEtagMixIn
    from djangodav.fs.resources import BaseFSDavResource

    class MyFSDavResource(MetaEtagMixIn, BaseFSDavResource):
        root = '/path/to/folder'

        def read(self):
            return open(self.get_abs_path(), 'rb')

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

2. Register WebDav view in urls.py

.. code:: python

    from djangodav.acls import FullAcl
    from djangodav.locks import DummyLock
    from djangodav.views import DavView

    from django.urls import re_path

    from .resource import MyFSDavResource

    # include fsdav/webdav without trailing slash (do not use a slash like in 'fsdav/(?P<path>.*)$')
    urlpatterns += 
        re_path(r'^fsdav(?P<path>.*)$', DavView.as_view(resource_class=MyFSDavResource, lock_class=DummyLock,
         acl_class=FullAcl))
    


Example 2: Create a simple database webdav resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This example is a bit more complex, as it requires two Django models and some handling.

1. Create the following models in models.py

.. code:: python

    from django.db import models
    from django.utils.timezone import now


    class BaseWebDavModel(models.Model):
        name = models.CharField(max_length=255)
        created = models.DateTimeField(default=now)
        modified = models.DateTimeField(default=now)

        class Meta:
            abstract = True


    class CollectionModel(BaseWebDavModel):
        parent = models.ForeignKey('self', blank=True, null=True)
        size = 0

        class Meta:
            unique_together = (('parent', 'name'),)

        def __str__(self):
            return "Collection {}".format(self.name)


    class ObjectModel(BaseWebDavModel):
        parent = models.ForeignKey(CollectionModel, blank=True, null=True)
        path = models.FileField(max_length=255)
        size = models.IntegerField(default=0)
        md5 = models.CharField(max_length=255)

        class Meta:
            unique_together = (('parent', 'name'),)

        def __str__(self):
            return "Object {}".format(self.name)



2. Create resources.py

.. code:: python

    from hashlib import md5

    from django.conf import settings
    from djangodav.db.resources import NameLookupDBDavMixIn, BaseDBDavResource

    from .models import CollectionModel, ObjectModel

    class MyDBDavResource(NameLookupDBDavMixIn, BaseDBDavResource):
        collection_model = CollectionModel
        object_model = ObjectModel

        root = "/path/to/folder"

        def write(self, request, temp_file=None):
            size = len(request.body)

            # calculate a hashsum of the request (ToDo: probably need to replace this with SHA1 or such, and maybe add a salt)
            hashsum = md5(request.body).hexdigest()

            # save the file
            new_path = os.path.join(settings.MEDIA_ROOT, self.displayname)

            f = open(new_path, 'wb')
            f.write(request.body)
            f.close()

            if not self.exists:
                obj = self.object_model(
                    name=self.displayname,
                    parent=self.get_parent().obj,
                    md5=hashsum,
                    size=size
                )

                obj.path.name = new_path

                obj.save()

                return

            self.obj.size = size
            self.obj.modified = now()
            self.obj.path.name = new_path
            self.obj.md5 = hashsum

            self.obj.save(update_fields=['path', 'size', 'modified', 'md5'])

        def read(self):
            return self.obj.path

        @property
        def etag(self):
            return self.obj.md5

        @property
        def getcontentlength(self):
            return self.obj.size



3. Register WebDav view in urls.py

.. code:: python

    from djangodav.acls import FullAcl
    from djangodav.locks import DummyLock
    from djangodav.views import DavView

    from django.urls import re_path

    from .resource import MyDBDavResource

    # include fsdav/webdav without trailing slash (do not use a slash like in 'dbdav/(?P<path>.*)$')
    urlpatterns += 
        re_path(r'^dbdav(?P<path>.*)$', DavView.as_view(resource_class=MyFSDavResource, lock_class=DummyLock,
         acl_class=FullAcl)),
    )
