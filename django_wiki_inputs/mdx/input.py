from django.contrib.auth.models import User
from django.db.models import Q
import markdown
from django.template.loader import render_to_string
import pyparsing as pp
from pathlib import Path
import ipdb  # NOQA
import logging

from .. import misc

logger = logging.getLogger(__name__)
pp.ParserElement.setDefaultWhitespaceChars(' \t')

pident = pp.Combine(pp.Word(pp.alphas, pp.alphas+pp.nums) + pp.ZeroOrMore("_" + pp.Word(pp.alphas+pp.nums)))
pfname = pp.Word(pp.alphas+pp.nums, pp.alphas+pp.nums+"-_.")

pint = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)).setParseAction(lambda i: int(i[0]))
pfloat = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)+pp.Literal('.')+pp.Word(pp.nums)).setParseAction(lambda f: float(f[0]))
pstr = pp.quotedString.setParseAction(lambda s: str(s[0]).strip('"'))

ppath = pp.Group(
    "." ^ (pp.Optional("/") + pp.ZeroOrMore((pfname ^ "..") + pp.Literal('/').suppress()).leaveWhitespace() + pfname.leaveWhitespace())
).setParseAction(lambda t: Path(*t[0]))

pmacro = pp.Combine(pp.Literal('_').suppress() + pp.Word(pp.alphas+pp.nums, pp.alphas+pp.nums+"_")).setParseAction(lambda t: dict(macro=t[0].rstrip('_')))
pinput = (pp.Literal('[').suppress()
          + pp.CaselessKeyword('input').setResultsName('cmd')  # NOQA
          + pident.setResultsName('name')  # NOQA
          + pp.Dict(pp.ZeroOrMore(pp.Group(pident + pp.Literal('=').suppress() + (pmacro ^ pint ^ pfloat ^ pstr ^ ppath)))).setResultsName('args')  # NOQA
          + pp.Literal(']').suppress()) # NOQA

pexpr = pp.Forward()
pexpr << pident.setResultsName('fname') + pp.Literal('(').suppress() + pp.delimitedList(pint ^ pfloat ^ pstr ^ ppath ^ pp.Group(pexpr), delim=",").setResultsName('args') + pp.Literal(')').suppress()

pdisplay = (pp.Literal('[').suppress() +  # NOQA
            pp.CaselessKeyword('display').setResultsName('cmd') + (ppath.setResultsName('path') ^ pp.Group(pexpr).setResultsName('fn')) +  # NOQA
            pp.Literal(']').suppress())

pparser = pinput ^ pdisplay


class InputExtension(markdown.Extension):
    """ Input plugin markdown extension for django-wiki. """

    def extendMarkdown(self, md, md_globals):
        """ Insert InputPreprocessor before ReferencePreprocessor. """
        md.preprocessors.add('dw-input', InputPreprocessor(md), '>html_block')


class InputPreprocessor(markdown.preprocessors.Preprocessor):
    """django-wiki input preprocessor - parse text for [input(-variant)?
    (args*)] references. """

    def __init__(self, *args, **kwargs):
        super(InputPreprocessor, self).__init__(*args, **kwargs)

        self.input_fields = list()
        if self.markdown:
            self.markdown.input_fields = self.input_fields

    # [f"{u.first_name} {u.last_name} <{u.email}>" for u in usrs]
    def expand_user_list(self, val):
        if 'macro' in val:
            if val['macro'] == 'all':
                qs = User.objects.all().order_by('last_name', 'first_name')
            else:
                qs = User.objects.filter(groups__name=val['macro'])
                if self.markdown.user:
                    qs |= User.objects.filter(pk=self.markdown.user.pk)

            return [u for u in qs.order_by('last_name', 'first_name')]
        else:
            return misc.dbsync_get_user(str(val['values']))


    def parse_select_user(self, args):
        if 'values' in args:
            args['values'] = self.expand_user_list(args['values'])

        if 'default' in args:
            args['default'] = misc.dbsync_get_user(str(args['default']))
        else:
            args['default'] = self.markdown.user


    def can_field(self, field, key):
        md = self.markdown

        # author of the article can everything
        if md.article.current_revision.user.pk == md.user.pk:
            return True

        if key not in field['args']:
            # if key is not set, just own inputs
            return True

        v = field['args'][key]
        if v == '_all_':
            return True

        # user is in the v group
        if v.startswith('_') and v.endswith('_'):
            return self.markdown.user.groups.filter(name=v.strip('_')).exists()
        else:
            return v == self.markdown.user.username or can_read == self.markdown.user.email


    def run(self, lines):
        doc = '\n'.join(lines)

        shift_n = 0

        for t, start, end in pparser.scanString(doc):
            field = t.asDict()
            field['id'] = len(self.input_fields)
            field['src'] = doc[(start+shift_n+1):(end+shift_n-1)]
            field['user'] = self.markdown.user

            html = ""
            if field['cmd'] == 'display':
                if self.markdown.preview:
                    html = render_to_string(f"wiki/plugins/inputs/preview.html", context=field)
                else:
                    html = render_to_string(f"wiki/plugins/inputs/display.html", context=field)

            elif field['cmd'] == 'input':
                if type(field['args']) == list:
                    assert len(field['args']) == 0
                    field['args'] = dict()

                if 'type' not in field['args']:
                    field['args']['type'] = 'text'

                if field['args']['type'] == 'select-user':
                    self.parse_select_user(field['args'])

                field['can_read'] = self.markdown.article.can_read(self.markdown.user) and self.can_field(field, 'can_read')

                field['can_write'] = field['can_read'] and self.can_field(field, 'can_write') and not self.markdown.article.current_revision.locked

                if field['can_read']:
                    if self.markdown.preview:
                        html = render_to_string(f"wiki/plugins/inputs/preview.html", context=field)
                    else:
                        html = render_to_string(f"wiki/plugins/inputs/input.html", context=field)

            html_repl = self.markdown.htmlStash.store(html, safe=True)
            doc = doc[:(start+shift_n)] + html_repl + doc[(end+shift_n):]

            shift_n -= end-start
            shift_n += len(html_repl)

            self.input_fields.append(field)

        return doc.split("\n")
