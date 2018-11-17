from django.contrib.auth.models import User
from wiki.models import URLPath
from wiki.core.markdown import ArticleMarkdown
from channels.db import database_sync_to_async
from collections import defaultdict
import logging
import asyncio
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
def db_get_article_markdown(article, user):
    md = ArticleMarkdown(article, preview=True, user=user)
    md.convert(article.current_revision.content)
    return md


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

    m = user_re.match(name)
    if m:
        try:
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
        self.input_cv = dict()
        self.render_lock = asyncio.Lock()

    async def get_markdown(self, path, user):
        article = await db_get_article(path)
        if article is None:
            logger.debug(f"{user}@{path}: article does not exits")
            return None

        cid = article.current_revision.pk
        async with self.render_lock:
            try:
                return self.cache[(cid,user.pk)]
            except KeyError:
                pass

            logger.debug(f"{user}@{path}: render current version")
            md = await db_get_article_markdown(article, user)

            for field in md.input_fields:
                if field['cmd'] == 'input':
                    try:
                        field['cv'] = self.input_cv[(cid,user.pk,field['name'])]
                    except KeyError:
                        field['cv'] = asyncio.Condition()
                        self.input_cv[(cid,user.pk,field['name'])] = field['cv']

            self.cache[(cid,user.pk)] = md
            return md


def get_markdown_factory():
    if get_markdown_factory._mk is None:
        get_markdown_factory._mk = _MarkdownFactory()

    return get_markdown_factory._mk


get_markdown_factory._mk = None
