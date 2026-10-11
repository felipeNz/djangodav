#!/usr/bin/env python
#
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

from setuptools import setup, find_packages


setup(
    name='DjangoDav',
    version=__import__('djangodav').__version__,
    description=('A WebDav server for Django'),
    long_description = open('README.rst').read(),
    author='Christian Kreuzberger',
    author_email='ckreuzberger@anexia-it.com',
    url='https://github.com/anx-ckreuzberger/djangodav',
    packages=find_packages(),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Django',
        'Framework :: Django :: 6.1',
        'License :: OSI Approved :: GNU Affero General Public License v3',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    python_requires=">=3.12",
    install_requires=["Django>=6.1,<7.0", "defusedxml"],
    tests_require=["Django>=6.1,<7.0"],
    include_package_data=True,
    zip_safe=False,
    test_suite='runtests.runtests'
)
