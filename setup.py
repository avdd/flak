import re
import ast
from setuptools import setup

_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('flak/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(
        f.read().decode('utf-8')).group(1)))

setup(
    name='Flak',
    version=version,
    url='http://github.com/avdd/flak/',
    license='BSD',
    packages=['flak'],
    include_package_data=True,
    zip_safe=False,
    platforms='any',
    install_requires=[
        'Werkzeug>=0.7',
        'itsdangerous>=0.21',
        'click>=2.0',
    ],
    entry_points='''
        [console_scripts]
        flak=flak.cli:main
    '''
)

