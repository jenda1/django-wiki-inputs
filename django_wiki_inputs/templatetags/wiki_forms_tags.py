from __future__ import absolute_import, unicode_literals

from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe
from django.contrib.auth.models import User
import pprint
import uuid
import json
import base64
from django_wiki_inputs import models

import pygments

register = template.Library()

@register.simple_tag
def get_uuid():
    return str(uuid.uuid4())

@register.filter
@stringfilter
def codehilite(value, arg):
    try:
        lexer = pygments.lexers.get_lexer_for_mimetype(arg)
    except ValueError:
        try:
            lexer = pygments.lexers.guess_lexer(value)
        except ValueError:
            lexer = pygments.lexers.TextLexer()

    return mark_safe(pygments.highlight(value, lexer, pygments.formatters.HtmlFormatter(cssclass="codehilite")))


@register.filter
@stringfilter
def b64decode(val):
    return base64.b64decode(val).decode('utf-8')

