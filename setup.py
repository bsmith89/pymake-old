from distutils.core import setup



setup(name='pymake',
      version='0.1.4',
      url='https://github.com/bsmith89/pymake',
      author='Byron J Smith',
      author_email='bsmith89@gmail.com',
      py_modules=['pymake'],
      package_dir = {'': 'lib'},
      install_requires=["termcolor"],
      extras_require={"visualize": ["pydot >= 1.0.15"]},
      dependency_links = ["hg+https://bitbucket.org/prologic/pydot"])
