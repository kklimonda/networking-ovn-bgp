import itertools

import networking_ovn_bgp.common.config


def list_opts():
    return [('DEFAULT',
             itertools.chain(
                 networking_ovn_bgp.common.config.base_opts
             ))]
