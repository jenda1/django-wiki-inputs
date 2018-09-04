import markdown
from django.template.loader import render_to_string
import pyparsing as pp
import ipdb  # NOQA
from pathlib import Path
import logging


logger = logging.getLogger(__name__)

# FIXME: pident pattern should not allow '_' at the end, the names are used internally
pident = pp.Combine(pp.Word(pp.alphas, pp.alphas+pp.nums) + pp.ZeroOrMore("_" + pp.Word(pp.alphas+pp.nums)))
pfname = pp.Word(pp.alphas+pp.nums+"-")

pint = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)).setParseAction(lambda i: int(i[0]))
pfloat = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)+pp.Literal('.')+pp.Word(pp.nums)).setParseAction(lambda f: float(f[0]))
pstr = pp.quotedString.addParseAction(pp.removeQuotes).addParseAction(lambda s: str(s[0]))

ppath = pp.Group(
    pp.Optional("/") + pp.ZeroOrMore((pfname ^ "..") + pp.Literal('/').suppress()) + pfname
).setParseAction(lambda t: Path(*t[0]))

ppath_full = pp.Group(
    ppath.setResultsName('path') + pp.Optional(pp.Literal('@').suppress() + (
        (pp.Literal("_") + pident.setResultsName('grp') + pp.Literal("_")) ^
        pident.setResultsName('usr'))).setResultsName('filter'))

pinput = (pp.Literal('[').suppress() +
          pp.CaselessKeyword('input').setResultsName('cmd') +
          pident.setResultsName('name') +
          pp.Dict(
              pp.ZeroOrMore(
                  pp.Group(
                      pident +
                      pp.Literal('=').suppress() +
                      (pint ^ pfloat ^ pstr)))).setResultsName('args') +
          pp.Literal(']').suppress())

pexpr = pp.Forward()
pexpr << pident.setResultsName('fname') + pp.Literal('(').suppress() + pp.delimitedList(pint ^ pfloat ^ pstr ^ ppath_full ^ pp.Group(pexpr), delim=",").setResultsName('args') + pp.Literal(')').suppress()

pdisplay = (pp.Literal('[').suppress() +
            pp.CaselessKeyword('display').setResultsName('cmd') + (
                ppath_full.setResultsName('fn').addParseAction(lambda t: dict(fname=None, args=[t.asDict()['fn']])) ^
                pp.Group(pexpr).setResultsName('fn')) +
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


    def run(self, lines):
        doc = '\n'.join(lines)

        shift_n = 0

        for t, start, end in pparser.scanString(doc):
            ctx = t.asDict()
            ctx['id'] = len(self.input_fields)
            ctx['src'] = doc[(start+shift_n+1):(end+shift_n-1)]

            tmpl = "preview.html" if self.markdown.preview else "input.html"
            html = render_to_string(f"wiki/plugins/inputs/{tmpl}", context=ctx)
            html_repl = self.markdown.htmlStash.store(html, safe=True)

            doc = doc[:(start+shift_n)] + html_repl + doc[(end+shift_n):]

            shift_n -= end-start
            shift_n += len(html_repl)

            self.input_fields.append(ctx)

        return doc.split("\n")
