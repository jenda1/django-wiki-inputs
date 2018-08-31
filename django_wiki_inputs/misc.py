from wiki.models import URLPath
from wiki.core.markdown import ArticleMarkdown
from channels.db import database_sync_to_async
from collections import defaultdict
import logging
import asyncio

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_get_article(path):
    p = URLPath.get_by_path(str(path))
    return p.article if p else None

@database_sync_to_async
def db_get_article_markdown(article):
    md = ArticleMarkdown(article, preview=True)     # FIXME: does the user= argument missing?
    md.convert(article.current_revision.content)
    md.article_revision_pk = article.current_revision.pk

    return md


#            if ctx['cmd'] == 'input':
#                if ctx['name'] in _input_cv[self.markdown.article.pk]:
#                    cv = _input_cv[self.markdown.article.pk][ctx['name']]
#                else:
#                    cv = asyncio.Condition()
#                    _input_cv[self.markdown.article.pk][ctx['name']] = cv
#
#                ctx['cv'] = cv


class _MarkdownFactory(object):
    def __init__(self):
        self.cache = dict()
        self._input_cv = defaultdict(dict)

    async def get_markdown(self, path, user):
        article = await db_get_article(path)
        if article is None or not article.can_read(user):
            return None

        try:
            md = self.cache[article.pk]
            if md.article_revision_pk == article.current_revision.pk:
                return md
        except KeyError:
            pass

        logger.debug(f"{user}@{path}: render current version")
        md = await db_get_article_markdown(article)

        for inp in md.input_fields:
            if inp['cmd'] == 'input':
                try:
                    inp['cv'] = self._input_cv[article.pk][inp['name']]
                except KeyError:
                    cv = asyncio.Condition()
                    self._input_cv[article.pk][inp['name']] = cv
                    inp['cv'] = cv

        self.cache[article.pk] = md

        return md


# class _InputCVFactory(object):
#     def __init__(self):
#         self.cache = defaultdict(dict)
#
#    async def get_input_cv(self, article, name):
#        try:
#            return self.cache[article.pk][name]
#        except KeyError:
#            pass
#
#        cv = asyncio.Condition()
#        self.cache[article.pk][name] = cv
#        return cv

markdown_factory = _MarkdownFactory()
