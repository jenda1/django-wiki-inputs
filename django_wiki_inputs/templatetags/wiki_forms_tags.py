import logging
from django.contrib.auth.models import User
from django import template
from django.template.defaultfilters import stringfilter
from django.utils.safestring import mark_safe
import uuid
import base64
import ipdb  # NOQA

import pygments
logger = logging.getLogger(__name__)

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

@register.filter
@stringfilter
def format_user(val):
    if val:
        if u.first_name and u.last_name:
            return f"{u.first_name} {u.last_name}"

        return val.username
