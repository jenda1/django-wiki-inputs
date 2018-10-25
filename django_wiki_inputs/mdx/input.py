from django.contrib.auth.models import User
import markdown
from django.template.loader import render_to_string
import pyparsing as pp
import ipdb  # NOQA
import logging

from .. import misc

logger = logging.getLogger(__name__)


pmacro = pp.Combine(pp.Literal('_').suppress() + pp.Word(pp.alphas+pp.nums, pp.alphas+pp.nums+"_")).setParseAction(lambda t: dict(macro=t[0].rstrip('_')))
pinput = (pp.Literal('[').suppress()
          + pp.CaselessKeyword('input').setResultsName('cmd')
          + misc.pident.setResultsName('name')
          + pp.Dict(
              pp.ZeroOrMore(
                  pp.Group(
                      misc.pident
                      + pp.Literal('=').suppress()
                      + (pmacro ^ misc.pint ^ misc.pfloat ^ misc.pstr ^ misc.ppath)))).setResultsName('args')
          + pp.Literal(']').suppress())

pexpr = pp.Forward()
pexpr << misc.pident.setResultsName('fname') + pp.Literal('(').suppress() + pp.delimitedList(misc.pint ^ misc.pfloat ^ misc.pstr ^ misc.ppath ^ pp.Group(pexpr), delim=",").setResultsName('args') + pp.Literal(')').suppress()

pdisplay = (pp.Literal('[').suppress() +
            pp.CaselessKeyword('display').setResultsName('cmd') + (misc.ppath.setResultsName('path') ^ pp.Group(pexpr).setResultsName('fn')) +
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

    def expand_macro(self, m):
        if m == 'all':
            usrs = User.objects.all().order_by('last_name', 'first_name')
        else:
            usrs = User.objects.filter(groups__name=m).order_by('last_name', 'first_name')

        return [f"{u.first_name} {u.last_name} <{u.email}>" for u in usrs]


    def run(self, lines):
        doc = '\n'.join(lines)

        shift_n = 0

        for t, start, end in pparser.scanString(doc):
            ctx = t.asDict()
            ctx['id'] = len(self.input_fields)
            ctx['src'] = doc[(start+shift_n+1):(end+shift_n-1)]

            if 'args' in ctx and 'values' in ctx['args']:
                if type(ctx['args']['values']) == dict and 'macro' in ctx['args']['values']:
                    ctx['args']['values'] = self.expand_macro(ctx['args']['values']['macro'])
                elif type(ctx['args']['values']) == str:
                    ctx['args']['values'] = [x.strip() for x in ctx['args']['values'].split(';')]

            tmpl = "preview.html" if self.markdown.preview else "input.html"
            html = render_to_string(f"wiki/plugins/inputs/{tmpl}", context=ctx)
            html_repl = self.markdown.htmlStash.store(html, safe=True)

            doc = doc[:(start+shift_n)] + html_repl + doc[(end+shift_n):]

            shift_n -= end-start
            shift_n += len(html_repl)

            self.input_fields.append(ctx)

        return doc.split("\n")
