from django.contrib.auth.models import User, Group
from wiki.models import URLPath
from wiki.core.markdown import ArticleMarkdown
from channels.db import database_sync_to_async
from collections import defaultdict
import logging
import asyncio
import pyparsing as pp
from pathlib import Path
from . import models
import re

import ipdb # NOQA

logger = logging.getLogger(__name__)

pp.ParserElement.setDefaultWhitespaceChars(' \t')

# FIXME: pident pattern should not allow '_' at the end, the names are used internally
pident = pp.Combine(pp.Word(pp.alphas, pp.alphas+pp.nums) + pp.ZeroOrMore("_" + pp.Word(pp.alphas+pp.nums)))
pfname = pp.Word(pp.alphas+pp.nums, pp.alphas+pp.nums+"-_.")

pint = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)).setParseAction(lambda i: int(i[0]))
pfloat = pp.Combine(pp.Optional('-')+pp.Word(pp.nums)+pp.Literal('.')+pp.Word(pp.nums)).setParseAction(lambda f: float(f[0]))
pstr = pp.quotedString.addParseAction(pp.removeQuotes).addParseAction(lambda s: str(s[0]))

ppath = pp.Group(
    "." ^ (pp.Optional("/") + pp.ZeroOrMore((pfname ^ "..") + pp.Literal('/').suppress()).leaveWhitespace() + pfname.leaveWhitespace())
).setParseAction(lambda t: Path(*t[0]))

ppath_full = pp.Group(
    ppath.setResultsName('path') + pp.Optional(pp.Literal('@').suppress() + (
        (pp.Literal("_") + pident.setResultsName('grp') + pp.Literal("_")) ^ pident.setResultsName('usr'))).setResultsName('filter'))


@database_sync_to_async
def db_get_article(path):
    try:
        return URLPath.get_by_path(str(path)).article
    except:
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


@database_sync_to_async
def db_get_user(name):
    try:
        return User.objects.get(username=name)
    except User.DoesNotExist:
        try:
            return User.objects.get(email=name)
        except User.DoesNotExist:
            return None


@database_sync_to_async
def db_get_input(article, name, user):
    return models.Input.objects.filter(
        article=article,
        owner=user,
        name=name).last()


@database_sync_to_async
def db_get_input_grp(article, name, grp):
    if grp is True:
        return models.Input.objects.filter(
            article=article,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')
    else:
        return models.Input.objects.filter(
            article=article,
            owner__group=grp,
            name=name).order_by('article', 'name', 'owner', '-created').distinct('article', 'name', 'owner')




email_re = re.compile(r'^.*?([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+).*$')

async def str_to_user(s):
    if s is None:
        return None

    try:
        m = email_re.match(s)
    except:
        ipdb.set_trace()

    if not m:
        return None

    return await db_get_user(m.group(1))



class _MarkdownFactory(object):
    def __init__(self):
        self.cache = dict()
        self._input_cv = defaultdict(dict)

    async def get_markdown(self, path, user):
        article = await db_get_article(path)
        if article is None:
            logger.debug(f"{user}@{path}: article does not exits")
            return None

        if not article.can_read(user):
            logger.debug(f"{user}@{path}: read forbidden")
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


markdown_factory = _MarkdownFactory()
