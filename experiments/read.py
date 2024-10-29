#!/usr/bin/env python

import io
import logging

from pymp4.parser import Box

log = logging.getLogger(__name__)

# read and write a file without modifying it

with open('hzd_frag_default.mp4', 'rb') as fd:
    fd.seek(0, io.SEEK_END)
    eof = fd.tell()
    fd.seek(0)

    with open('out.mp4', 'wb') as fo:
        while fd.tell() < eof:
            box = Box.parse_stream(fd)
            fo.write(Box.build(box))

