from django.contrib.auth.models import User
import markdown
from django.template.loader import render_to_string
import pyparsing as pp
from pathlib import Path
import ipdb  # NOQA
import logging

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


def query_user(val):
    vals = val.split()

    return User.objects.filter(
        Q(email=val) |
        Q(username=val) |
        (Q(first_name=vals[0]) & Q(last_name=vals[-1])) |
        Q(last_name=val) |
        Q(first_name=val)).first()


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
                return [u for u in User.objects.all().order_by('last_name', 'first_name')]
            else:
                return [u for u in User.objects.filter(groups__name=val['macro']).order_by('last_name', 'first_name')]
        else:
            return query_user(str(ctx['args']['values']))


    def parse_select_user(self, args):
        if 'values' in args:
            args['values'] = self.expand_user_list(args['values'])

        if 'default' in args:
            args['default'] = query_user(str(args['default']))
        else:
            args['default'] = self.markdown.user


    def run(self, lines):
        doc = '\n'.join(lines)

        shift_n = 0

        for t, start, end in pparser.scanString(doc):
            ctx = t.asDict()
            ctx['id'] = len(self.input_fields)
            ctx['src'] = doc[(start+shift_n+1):(end+shift_n-1)]
            ctx['user'] = self.markdown.user

            if ctx['cmd'] == 'input':
                if type(ctx['args']) == list:
                    assert len(ctx['args']) == 0
                    ctx['args'] = dict()

                if 'type' not in ctx['args']:
                    ctx['args']['type'] = 'text'

                if ctx['args']['type'] == 'select-user':
                    self.parse_select_user(ctx['args'])

                if 'can_read' in ctx['args']:
                    ctx['args']['can_read'] = self.expand_user_list(ctx['args']['can_read'])

            tmpl = "preview.html" if self.markdown.preview else "input.html"
            html = render_to_string(f"wiki/plugins/inputs/{tmpl}", context=ctx)
            html_repl = self.markdown.htmlStash.store(html, safe=True)

            doc = doc[:(start+shift_n)] + html_repl + doc[(end+shift_n):]

            shift_n -= end-start
            shift_n += len(html_repl)

            self.input_fields.append(ctx)

        return doc.split("\n")
