from enum import Enum

import requests

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
        registry.subscribe(self.update_floatingip_postcommit, resources.ROUTER_INTERFACE,
                           events.AFTER_UPDATE)
        registry.subscribe(self.update_floatingip_postcommit, resources.ROUTER_GATEWAY,
                           events.AFTER_UPDATE)

    def get_plugin_description(self):
        return "L3 Router Service Plugin for basic OVN-BGP integration"

    def get_plugin_type(self):
        return "ovn-bgp"

    def _notify_bgp_speakers(self, floating_ip, event):
        speakers = cfg.CONF.ovn_bgp_speakers
        post_data = {"event": event.value, "ip_address": floating_ip}

        for speaker in speakers:
            requests.post(speaker, json=post_data)

    def _log_debug_data(self, func, resource, event, trigger, **kwargs):
        LOG.info(func.__name__)
        LOG.info("\tresource = %s" % resource)
        LOG.info("\tevent = %s" % event)
        LOG.info("\ttrigger = %s" % trigger)
        for key, value in kwargs.items():
            LOG.info("\t%s = %s" % (key, value))

    def update_floatingip_postcommit(self, *args, **kwargs):
        self._log_debug_data(self.update_floatingip_postcommit, *args, **kwargs)

        router_id = kwargs.get("router_id", None)
        last_known_router_id = kwargs.get("last_known_router_id", None)
        floating_ip_address = kwargs.get("floating_ip_address")

        event = NeutronEvent.UNKNOWN
        if router_id and not last_known_router_id:
            event = NeutronEvent.ANNOUNCE
        elif not router_id and last_known_router_id:
            event = NeutronEvent.WITHDRAW

        if event == NeutronEvent.ANNOUNCE:
            log_action = "attached to"
        else:
            log_action = "detached from"

        LOG.info(("Floating IP %s has been %s a port. "
                  "Updating BGP speakers."),
                 floating_ip_address, log_action)
        self._notify_bgp_speakers(floating_ip_address, event)

    def delete_floatingip_postcommit(self, *args, **kwargs):
        self._log_debug_data(self.delete_floatingip_postcommit, *args, **kwargs)

        floating_ip_adderss = kwargs.get("floating_ip_address")
        event = NeutronEvent.DISSOCIATE

        LOG.info("Floating IP %s has been deleted. Updating BGP speakers",
                 floating_ip_adderss)
        self._notify_bgp_speakers(floating_ip_adderss, event)

    def update_router_gateway_postcommit(self, *args, **kwargs):
        self._log_debug_data(self.update_router_gateway_postcommit, *args, **kwargs)
