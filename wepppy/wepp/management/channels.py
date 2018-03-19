import os
from os.path import join as _join

from pprint import pprint

_thisdir = os.path.dirname(__file__)
_datadir = _join(_thisdir, 'data')


def load_channels():
    """
    loads the channel soil managements from the channel.defs file
    These are assigned based on the order of the channel and are
    needed to make the pw0.chn for the watershed run
    """
    global _datadir
    with open(_join(_datadir, 'channels.defs')) as fp:
        blocks = fp.read()
        
    d = {}
    blocks = blocks.split('\n\n')
    for block in blocks:
        block = block.strip().split('\n')
        key = block[0]
        desc = block[1]
        contents = block[2:-2]
        contents[3] = '\n'.join(contents[3].split())
        contents[4] = ' '.join(['%0.5f' % float(v) for v in contents[4].split()])
        contents[5] = ' '.join(['%0.5f' % float(v) for v in contents[5].split()])
        contents[6] = ' '.join(['%0.5f' % float(v) for v in contents[6].split()])
#        contents[7] = ' '.join(['%0.5f' % float(v) for v in contents[7].split()])
        contents = '\n'.join(contents)
        rot = block[-1]
        d[key] = dict(key=key, desc=desc, contents=contents, rot=rot)
        
    return d


def get_channel(key):
    d = load_channels()
    return d[key]


if __name__ == "__main__":
    load_channels()
    
    pprint(get_channel('DITCH 1'))
