from django.db.models import Q
from django.contrib.auth.models import User
from wiki.models import URLPath
from wiki.core.markdown import ArticleMarkdown
from channels.db import database_sync_to_async
import logging
import pathlib
import asyncio
import re
import os

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
def dbsync_get_user(name):
    names = name.split(name)

    q = Q(username=name) | Q(email=name)
    if len(names) == 2:
        q |= (Q(first_name=names[0]) & Q(last_name=names[-1]))
    q |= Q(last_name=name) | Q(first_name=name)

    m = user_re.match(name)
    if m:
        q |= Q(email=m.group(2))

    return User.objects.filter(q).first()


@database_sync_to_async
def db_get_user(name):
    return dbsync_get_user(name)


@database_sync_to_async
def db_is_user_in_group(user, name):
    return user.groups.filter(name=name).exists()


email_re = re.compile(r'^.*?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+).*$')

async def str_to_user(s):
    if s is None:
        return None

    m = email_re.match(s)
    if not m:
        return None

    return await db_get_user(m.group(1))


def normpath(ic, path):
    return pathlib.Path(os.path.normpath(os.path.join(ic.path, str(path))))


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
                return self.cache[(cid, user.pk)]
            except KeyError:
                pass

            logger.debug(f"{user}@{path}: render current version")
            md = await db_get_article_markdown(article, user)

            for field in md.input_fields:
                if field['cmd'] == 'input':
                    try:
                        field['cv'] = self.input_cv[(cid, field['name'])]
                    except KeyError:
                        field['cv'] = asyncio.Condition()
                        self.input_cv[(cid, field['name'])] = field['cv']

            self.cache[(cid, user.pk)] = md
            return md


def get_markdown_factory():
    if get_markdown_factory._mk is None:
        get_markdown_factory._mk = _MarkdownFactory()

    return get_markdown_factory._mk


get_markdown_factory._mk = None
