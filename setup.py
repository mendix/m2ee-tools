from distutils.core import setup
import setuptools

setup(
    name='m2ee',
    package_dir = {'': 'src'},
    packages=setuptools.find_packages('src'),
)
