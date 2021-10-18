import requests

from enum import Enum
from netaddr import IPAddress
from requests.auth import HTTPBasicAuth

from neutron_lib.callbacks import events
from neutron_lib.callbacks import registry
from neutron_lib.callbacks import resources
from neutron_lib.services import base as service_base
from oslo_config import cfg
from oslo_log import log

import networking_ovn_bgp.common.config

LOG = log.getLogger(__name__)


class NeutronEvent(Enum):
    ANNOUNCE = "announce"
    WITHDRAW = "withdraw"
    UNKNOWN = "unknown"


class OVNBGPL3RouterPlugin(service_base.ServicePluginBase):
    supported_extension_aliases = []

    def __init__(self):
        super(OVNBGPL3RouterPlugin, self).__init__()
        LOG.info("Starting OVNBGPL3RouterPlugin")
        self._register_postcommit_callbacks()
        self._register_opts()

    @staticmethod
    def _register_opts():
        cfg.CONF.register_opts(networking_ovn_bgp.common.config.base_opts)

    def _register_postcommit_callbacks(self):
        registry.subscribe(self.update_floatingip_postcommit, resources.FLOATING_IP,
                           events.AFTER_UPDATE)
        registry.subscribe(self.delete_floatingip_postcommit, resources.FLOATING_IP,
                           events.AFTER_DELETE)
        registry.subscribe(self.update_router_gateway_postcommit, resources.ROUTER_GATEWAY,
                           events.AFTER_CREATE)
        registry.subscribe(self.update_router_gateway_postcommit, resources.ROUTER_GATEWAY,
                           events.AFTER_DELETE)

    def get_plugin_description(self):
        return "L3 Router Service Plugin for basic OVN-BGP integration"

    def get_plugin_type(self):
        return "ovn-bgp"

    def _notify_bgp_speakers(self, floating_ip, event):
        speakers = cfg.CONF.ovn_bgp_speakers
        post_data = {"event": event.value, "ip_address": floating_ip}
        LOG.debug("JSON payload: %s", str(post_data))
        auth = HTTPBasicAuth(cfg.CONF.ovn_bgp_username,
                             cfg.CONF.ovn_bgp_password)
        for speaker in speakers:
            response = requests.post(speaker, auth=auth, json=post_data,
                                     verify=not cfg.CONF.ovn_bgp_insecure,
                                     timeout=cfg.CONF.ovn_bgp_api_server_timeout)
            LOG.debug(response)

    def _log_debug_data(self, func, resource, event, trigger, **kwargs):
        LOG.debug(func.__name__)
        LOG.debug("\tresource = %s" % resource)
        LOG.debug("\tevent = %s" % event)
        LOG.debug("\ttrigger = %s" % trigger)
        for key, value in kwargs.items():
            LOG.debug("\t%s = %s" % (key, value))
            if key == "payload":
                for ikey, ivalue in value.metadata.items():
                    LOG.debug("\t\t%s = %s" % (ikey, ivalue))

    def update_floatingip_postcommit(self, *args, **kwargs):
        self._log_debug_data(self.update_floatingip_postcommit, *args, **kwargs)

        router_id = kwargs.get("router_id", None)
        last_known_router_id = kwargs.get("last_known_router_id", None)
        floating_ip_address = kwargs.get("floating_ip_address")

        if router_id and not last_known_router_id:
            event = NeutronEvent.ANNOUNCE
        elif not router_id and last_known_router_id:
            event = NeutronEvent.WITHDRAW
        else:
            LOG.debug(("Floating IP %s has been created but not attached "
                       "to any port yet. Not announcing for now"),
                      floating_ip_address)
            return

        if event == NeutronEvent.ANNOUNCE:
            log_action = "attached to"
        else:
            log_action = "detached from"

        LOG.info(("Floating IP %s has been %s a port. "
                  "Updating BGP speakers."),
                 floating_ip_address, log_action)
        self._notify_bgp_speakers(str(floating_ip_address), event)

    def delete_floatingip_postcommit(self, *args, **kwargs):
        self._log_debug_data(self.delete_floatingip_postcommit, *args, **kwargs)

        floating_ip_adderss = kwargs.get("floating_ip_address")
        event = NeutronEvent.WITHDRAW

        LOG.info("Floating IP %s has been deleted. Updating BGP speakers",
                 floating_ip_adderss)
        self._notify_bgp_speakers(floating_ip_adderss, event)

    def update_router_gateway_postcommit(self, resource, event, trigger, **kwargs):
        self._log_debug_data(self.update_router_gateway_postcommit,
                             resource, event, trigger, **kwargs)
        # FIXME: gateway_ips can have more than one IP, but it's probably
        #        used for dual stack routers, so assume there is only one.
        gateway_ip = None
        gateway_ips = kwargs["payload"].metadata["gateway_ips"]
        if len(gateway_ips) > 1:
            for ip in gateway_ips:
                if IPAddress(ip).version == 4:
                    gateway_ip = ip
                    break
        else:
            gateway_ip = gateway_ips[0]
        if not gateway_ip:
            LOG.error("Unable to get v4 gateway IP for router, IPs available are: %s" % ", ".join(gateway_ips))
            return

        if event == "after_create":
            LOG.info("Router gateway IP %s assigned. Updating BGP speakers" % gateway_ip)
            self._notify_bgp_speakers(str(gateway_ip), NeutronEvent.ANNOUNCE)
        else:
            LOG.info("Router gateway IP %s removed. Updating BGP speakers" % gateway_ip)
            self._notify_bgp_speakers(str(gateway_ip), NeutronEvent.WITHDRAW)
