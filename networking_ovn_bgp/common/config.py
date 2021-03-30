from oslo_config import cfg

base_opts = [
    cfg.MultiStrOpt("ovn_bgp_speakers", required=True),
    cfg.BoolOpt("ovn_bgp_insecure", default=False),
    cfg.StrOpt("ovn_bgp_username", required=True),
    cfg.StrOpt("ovn_bgp_password", required=True),
]
