ak-pytools
==========

Summary
-------
Personal python package with helper modules to be used in my scripts


Installation:
-------------

1. Checkout the source code:
```
    cd ~/some_location
    git clone https://github.com/akorshkov/ak_py.git
```
2. Install it into current python environment:
```
    pip install --user -e ~/the_location/ak_py/
```
3. Install optional dependencies:
```
    pip install --user openpyxl
    pip install --user mysql-connector-python
    pip install --user gitpython
```
4. Use it:
```
    python
    >>> from ak import color
    >>> print(color.make_examples())
```
