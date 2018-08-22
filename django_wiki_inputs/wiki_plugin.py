from __future__ import absolute_import, unicode_literals

from django.utils.translation import ugettext as _
from wiki.core.plugins import registry
from wiki.core.plugins.base import BasePlugin
from . import settings
from .mdx.input import InputExtension

import ipdb  # NOQA

import logging
logger = logging.getLogger(__name__)



class InputsPlugin(BasePlugin):

    slug = settings.SLUG

    urlpatterns = {
        'article': list(),
        'root': list()
    }

    sidebar = {'headline': _('Inputs'),
               'icon_class': 'fa-pencil-square-o',
               'template': 'wiki/plugins/inputs/sidebar.html',
               'form_class': None,
               'get_form_kwargs': (lambda a: {})}

    class RenderMedia:
        js = [
            'channels/js/websocketbridge.js',
            'wiki/js/dw-inputs.js',
        ]

        css = {
            'all': 'wiki/css/dw-inputs.css',
        }

    markdown_extensions = [InputExtension()]

    html_whitelist = ['input', 'textarea', 'span', 'kbd']
    html_attributes = {
        'input': ['data-id', 'data-user', 'value', 'class', 'id', 'type', 'disabled', 'multiple'],
        'textarea': ['data-id', 'class', 'id', 'type', 'disabled', 'multiple'],
        'span': ['data-id', 'data-listen', 'class', 'id'],
        'kbd': ['class'],
    }


registry.register(InputsPlugin)
