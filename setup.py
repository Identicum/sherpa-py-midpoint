# sherpa-py-midpoint is available under the MIT License. https://github.com/Identicum/sherpa-py-midpoint/
# Copyright (c) 2024, Identicum - https://identicum.com/
#
# Author: Gustavo J Gallardo - ggallard@identicum.com
#

from setuptools import setup

setup(
    name='sherpa-py-midpoint',
    version='1.1.0-20250422',
    description='Python utilities for Midpoint',
    url='git@github.com:Identicum/sherpa-py-midpoint.git',
    author='Identicum',
    author_email='ggallard@identicum.com',
    license='MIT License',
    install_requires=['requests'],
    packages=['sherpa.midpoint'],
    zip_safe=False,
    python_requires='>=3.0'
)
