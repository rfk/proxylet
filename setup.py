#
#  This is the proxylet setuptools script.
#  Originally written by Ryan Kelly, 2007.
#
#  This sript is placed in the public domain.
#


import ez_setup
ez_setup.use_setuptools()

from setuptools import setup, find_packages

try:
    import proxylet
except ImportError:
    version = "0.0.0"
    long_desc = ""
else:
    version = proxylet.__version__
    long_desc = proxylet.__doc__
    del proxylet


setup(name='proxylet',
      version=version,
      description='Lightweight HTTP reverse proxy built on eventlet',
      long_description=long_desc,
      classifiers = [
      ],
      keywords = "HTTP reverse proxy",
      author = "Ryan Kelly",
      author_email = "ryan@rfk.id.au",
      packages = find_packages(),
      license = "PSF",
      install_requires = [
        'Paste','eventlet'
      ],
      )
