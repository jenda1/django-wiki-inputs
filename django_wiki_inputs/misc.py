from django.contrib.auth.models import User, Group
from wiki.models import URLPath
from wiki.core.markdown import ArticleMarkdown
from channels.db import database_sync_to_async
from collections import defaultdict
import logging
import asyncio
from . import models
import re

import ipdb # NOQA

logger = logging.getLogger(__name__)


@database_sync_to_async
def db_get_article(path):
    try:
        return URLPath.get_by_path(str(path)).article
    except Exception:
        return None

@database_sync_to_async
def db_get_article_markdown(article):
    md = ArticleMarkdown(article, preview=True)     # FIXME: does the user= argument missing?
    md.convert(article.current_revision.content)
    md.article_revision_pk = article.current_revision.pk

    return md


@database_sync_to_async
def db_get_group(name):
    try:
        return Group.objects.get(name=name)
    except Group.DoesNotExist:
        return None

user_re = re.compile(r"^(.+) <(.+)>$")

@database_sync_to_async
def db_get_user(name):
    try:
        return User.objects.get(username=name)
    except User.DoesNotExist:
        pass

    try:
        return User.objects.get(email=name)
    except User.DoesNotExist:
        pass

    try:
        m = user_re.match(name)
        if m:
            return User.objects.get(email=m.group(2))
    except User.DoesNotExist:
        pass


email_re = re.compile(r'^.*?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+).*$')

async def str_to_user(s):
    if s is None:
        return None

    m = email_re.match(s)
    if not m:
        return None

    return await db_get_user(m.group(1))



class _MarkdownFactory(object):
    def __init__(self):
        self.cache = dict()
        self._input_cv = defaultdict(dict)
        self.render_lock = asyncio.Lock()

    async def get_markdown(self, path, user):
        article = await db_get_article(path)
        if article is None:
            logger.debug(f"{user}@{path}: article does not exits")
            return None

        if not article.can_read(user):
            logger.debug(f"{user}@{path}: read forbidden")
            return None

        async with self.render_lock:
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


def get_markdown_factory():
    if get_markdown_factory._mk is None:
        get_markdown_factory._mk = _MarkdownFactory()

    return get_markdown_factory._mk

get_markdown_factory._mk = None
