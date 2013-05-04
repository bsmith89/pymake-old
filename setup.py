from distutils.core import setup



setup(name='pymake',
      version='0.1.5',
      url='https://github.com/bsmith89/pymake',
      author='Byron J Smith',
      author_email='bsmith89@gmail.com',
      py_modules=['pymake'],
      package_dir = {'': 'lib'},
      install_requires=["termcolor"],
      extras_require={"FIG": ["pydot-py3 >= 1.0.15"]},
      dependency_links = [("git+https://github.com/bsmith89/"
                           "pydot-py3.git#egg=pydot-py3-1.0.15")])
