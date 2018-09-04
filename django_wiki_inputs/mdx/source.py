import markdown
import logging
import ipdb

logger = logging.getLogger(__name__)


class SourceExtension(markdown.Extension):
    """ Source plugin markdown extension for django-wiki. """

    def extendMarkdown(self, md, md_globals):
        """ Add SourcePostprocessor to Markdown instance. """
        src = SourceTreeprocessor(md)
        src.config = self.getConfigs()

        md.treeprocessors.add("source", src, "<hilite")

        #md.registerExtension(self)


def pp(e, sp=""):
    print(sp, e.tag, e.attrib, e.text)

    for b in e:
        pp(b, sp + "    ")


class SourceTreeprocessor(markdown.treeprocessors.Treeprocessor):
    """django-wiki source preprocessor
    """

    def __init__(self, *args, **kwargs):
        super(SourceTreeprocessor, self).__init__(*args, **kwargs)
        self.source_fields = dict()

        if self.markdown:
            self.markdown.source_fields = self.source_fields

    def run(self, root):
        """ Find code blocks and store in htmlStash. """
        #pp(root)
        for block in root:
            if block.tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                name = block.text

            if block.tag == 'pre' and len(block) > 0 and block[0].tag == 'code':
                txt = block[0].text
                if txt.startswith('::'):
                    txt = txt.split('\n', 1)[1]

                self.source_fields[name] = txt
